"""Exercise matching, retention, exemplar review and human SKU review together.

The matching worker holds the target/source image, product and approved-exemplar
locks while three independent API requests attempt retention, pending-exemplar
review and human detection review. The smoke observes all three requests blocked
by the worker PID in pg_stat_activity before releasing it, then verifies that
the requests finish without a deadlock and that persisted state/audit are sound.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic, sleep
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.product_embedding_service import (
    build_approved_product_registry,
    lock_matching_source_images,
)
from app.security import create_access_token


def _bearer(user_id: int, role: str) -> dict[str, str]:
    token, _ = create_access_token(user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


def _fixture(suffix: str) -> dict[str, int]:
    with SessionLocal() as db:
        store = models.Store(code=f"PG-FOUR-WAY-{suffix}", name="Four-way smoke")
        product = models.Product(
            sku=f"PG-FOUR-WAY-SKU-{suffix}",
            name="Four-way concurrency product",
            is_active=True,
        )
        admin = models.User(
            email=f"pg-four-way-admin-{suffix}@example.test",
            full_name="Four-way smoke administrator",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        creator = models.User(
            email=f"pg-four-way-creator-{suffix}@example.test",
            full_name="Four-way smoke creator",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=None,
            is_active=True,
        )
        db.add_all([store, product, admin, creator])
        db.flush()
        zone = models.Zone(store_id=store.id, name="Four-way smoke zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"PG-4W-{suffix}")
        db.add(shelf)
        db.flush()
        db.add(models.ShelfProduct(
            shelf_id=shelf.id, product_id=product.id,
            target_quantity=10, min_display_quantity=1,
        ))
        source = models.ShelfImage(
            shelf_id=shelf.id, original_filename="approved-reference.jpg",
            storage_path=f"/tmp/pg-four-way-source-{suffix}.jpg",
            mime_type="image/jpeg", file_size_bytes=10,
            sha256="d" * 64, retention_status="ACTIVE",
        )
        target = models.ShelfImage(
            shelf_id=shelf.id, original_filename="worker-target.jpg",
            storage_path=f"/tmp/pg-four-way-target-{suffix}.jpg",
            mime_type="image/jpeg", file_size_bytes=10,
            sha256="e" * 64, retention_status="ACTIVE",
        )
        db.add_all([source, target])
        db.flush()
        approved = models.ProductEmbeddingExemplar(
            product_id=product.id, shelf_image_id=source.id,
            embedding=[1.0, 0.0, 0.0], embedding_dimension=3,
            model_version="pg-four-way-v1", image_sha256="d" * 64,
            licence="store-owned-smoke-reference", review_status="APPROVED",
            created_by_user_id=creator.id, reviewed_by_user_id=admin.id,
            reviewed_at=models.utc_now(),
        )
        pending = models.ProductEmbeddingExemplar(
            product_id=product.id, shelf_image_id=source.id,
            embedding=[0.0, 1.0, 0.0], embedding_dimension=3,
            model_version="pg-four-way-v2", image_sha256="f" * 64,
            licence="store-owned-smoke-reference", review_status="PENDING",
            created_by_user_id=creator.id,
        )
        detection = models.ShelfImageDetection(
            shelf_image_id=target.id, product_id=product.id,
            label="product", confidence=0.99,
            x_min=0.1, y_min=0.1, x_max=0.9, y_max=0.9,
            model_version="pg-four-way-detector-v1",
            sku_match_status="MATCHED",
        )
        db.add_all([approved, pending, detection])
        db.commit()
        return {
            "product_id": product.id, "admin_id": admin.id,
            "source_image_id": source.id, "target_image_id": target.id,
            "approved_exemplar_id": approved.id,
            "pending_exemplar_id": pending.id, "detection_id": detection.id,
        }


def main() -> None:
    suffix = uuid4().hex[:10]
    data = _fixture(suffix)
    worker_name = f"ss-four-way-{suffix}"
    worker_locked, release_worker = Event(), Event()
    request_barrier = Barrier(3)
    worker_pid_holder: list[int] = []

    def matching_worker() -> None:
        with SessionLocal() as db:
            db.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": worker_name},
            )
            worker_pid_holder.append(
                db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            lock_matching_source_images(
                db, target_image_id=data["target_image_id"],
                model_versions={"pg-four-way-v1"},
            )
            registry = build_approved_product_registry(
                db, model_version="pg-four-way-v1",
            )
            match = registry.match([1.0, 0.0, 0.0])
            assert match.status == "MATCHED", match
            worker_locked.set()
            if not release_worker.wait(timeout=25):
                raise TimeoutError("matching worker was not released")
            db.commit()

    def restrict_source_image():
        request_barrier.wait(timeout=10)
        with TestClient(app) as client:
            return client.post(
                f"/api/v1/shelf-images/{data['source_image_id']}/retention/restrict",
                json={"reason": "Four-way PostgreSQL concurrency smoke"},
                headers=_bearer(data["admin_id"], "ADMIN"),
            )

    def review_pending_exemplar():
        request_barrier.wait(timeout=10)
        with TestClient(app) as client:
            return client.patch(
                f"/api/v1/product-embedding-exemplars/{data['pending_exemplar_id']}/review",
                json={
                    "review_status": "APPROVED",
                    "review_notes": "Four-way PostgreSQL concurrency smoke",
                },
                headers=_bearer(data["admin_id"], "ADMIN"),
            )

    def review_detection():
        request_barrier.wait(timeout=10)
        with TestClient(app) as client:
            return client.post(
                f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
                json={"decision": "CONFIRMED", "notes": "Four-way PostgreSQL concurrency smoke"},
                headers=_bearer(data["admin_id"], "ADMIN"),
            )

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(update={"app_env": "production"})
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            worker_future = executor.submit(matching_worker)
            assert worker_locked.wait(timeout=15), (
                "matching worker did not acquire image/product/exemplar locks"
            )
            api_futures = [
                executor.submit(restrict_source_image),
                executor.submit(review_pending_exemplar),
                executor.submit(review_detection),
            ]
            try:
                deadline = monotonic() + 20
                observed_waiters = 0
                while monotonic() < deadline:
                    with SessionLocal() as monitor:
                        observed_waiters = monitor.execute(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE wait_event_type = 'Lock' "
                                "AND :worker_pid = ANY(pg_blocking_pids(pid))"
                            ),
                            {"worker_pid": worker_pid_holder[0]},
                        ).scalar_one()
                    if observed_waiters >= 3:
                        break
                    if any(future.done() for future in api_futures):
                        break
                    sleep(0.05)
                assert observed_waiters >= 3, (
                    "expected all three API operations to wait on matching worker; "
                    f"observed {observed_waiters}"
                )
            finally:
                release_worker.set()

            worker_future.result(timeout=20)
            retention_response, exemplar_response, detection_response = [
                future.result(timeout=30) for future in api_futures
            ]

        assert retention_response.status_code == 200, retention_response.text
        assert exemplar_response.status_code in {200, 410}, exemplar_response.text
        assert detection_response.status_code == 201, detection_response.text

        with SessionLocal() as db:
            source = db.get(models.ShelfImage, data["source_image_id"])
            target = db.get(models.ShelfImage, data["target_image_id"])
            pending = db.get(models.ProductEmbeddingExemplar, data["pending_exemplar_id"])
            approved = db.get(models.ProductEmbeddingExemplar, data["approved_exemplar_id"])
            assert source.retention_status == "RESTRICTED"
            assert target.retention_status == "ACTIVE"
            assert approved.review_status == "APPROVED"
            if exemplar_response.status_code == 200:
                assert pending.review_status == "APPROVED"
                assert pending.reviewed_by_user_id == data["admin_id"]
                assert pending.reviewed_at is not None
            else:
                assert pending.review_status == "PENDING"

            retention_events = db.query(models.ShelfImageRetentionEvent).filter(
                models.ShelfImageRetentionEvent.shelf_image_id == data["source_image_id"],
                models.ShelfImageRetentionEvent.event_type == "RESTRICTED",
            ).count()
            detection_reviews = db.query(models.DetectionSkuReview).filter(
                models.DetectionSkuReview.detection_id == data["detection_id"]
            ).all()
            assert retention_events == 1, retention_events
            assert len(detection_reviews) == 1, detection_reviews
            assert detection_reviews[0].decision == "CONFIRMED"
            assert detection_reviews[0].selected_product_id == data["product_id"]

        print(
            "PostgreSQL four-way concurrency smoke passed: matching blocked all "
            "three competing API transactions; all completed without a deadlock, "
            "and persisted states/audit records were verified."
        )
    finally:
        release_worker.set()
        main_module.settings = original_settings


if __name__ == "__main__":
    main()
