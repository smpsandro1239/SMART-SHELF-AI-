"""Prove detection and exemplar IDs are tenant-authorized before PostgreSQL locks.

A supervisor from store A supplies real detection/exemplar IDs belonging to
store B while the source image and global product rows are locked. All direct-ID
operations must return HTTP 403 without waiting for either lock or mutating data.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token


def create_fixture(suffix: str) -> tuple[int, int, int, int, int]:
    with SessionLocal() as db:
        store_a = models.Store(code=f"PRELOCK-A-{suffix}", name="Pre-lock tenant A")
        store_b = models.Store(code=f"PRELOCK-B-{suffix}", name="Pre-lock tenant B")
        db.add_all([store_a, store_b])
        db.flush()

        actor = models.User(
            email=f"prelock-actor-{suffix}@example.test",
            full_name="Store A supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store_a.id,
            is_active=True,
        )
        creator = models.User(
            email=f"prelock-creator-{suffix}@example.test",
            full_name="Exemplar creator",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        product = models.Product(
            sku=f"PRELOCK-SKU-{suffix}",
            name="Pre-lock authorization product",
            is_active=True,
        )
        db.add_all([actor, creator, product])
        db.flush()

        zone = models.Zone(store_id=store_b.id, name="Foreign zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"PRELOCK-{suffix}")
        db.add(shelf)
        db.flush()
        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="foreign-source.jpg",
            storage_path=f"/tmp/prelock-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="f" * 64,
            retention_status="ACTIVE",
            analysis_status="COMPLETED",
            model_version="detector-prelock-v1",
        )
        db.add(image)
        db.flush()
        detection = models.ShelfImageDetection(
            shelf_image_id=image.id,
            product_id=product.id,
            label="product",
            confidence=0.95,
            x_min=0.1,
            y_min=0.1,
            x_max=0.8,
            y_max=0.9,
            model_version="detector-prelock-v1",
        )
        exemplar = models.ProductEmbeddingExemplar(
            product_id=product.id,
            shelf_image_id=image.id,
            embedding=[1.0, 0.0, 0.0],
            embedding_dimension=3,
            model_version="embedding-prelock-v1",
            image_sha256="f" * 64,
            licence="store-owned-prelock-smoke",
            review_status="PENDING",
            created_by_user_id=creator.id,
        )
        db.add_all([detection, exemplar])
        db.commit()
        return actor.id, image.id, product.id, detection.id, exemplar.id


def main() -> None:
    suffix = uuid4().hex[:10]
    actor_id, image_id, product_id, detection_id, exemplar_id = create_fixture(suffix)
    token, _ = create_access_token(user_id=actor_id, role="SUPERVISOR")
    image_locked = Event()
    product_locked = Event()
    release_locks = Event()
    results: dict[str, int] = {}

    def hold_source_and_catalogue_locks() -> None:
        with SessionLocal() as db:
            db.execute(
                select(models.ShelfImage)
                .where(models.ShelfImage.id == image_id)
                .with_for_update()
            ).scalar_one()
            image_locked.set()
            db.execute(
                select(models.Product)
                .where(models.Product.id == product_id)
                .with_for_update()
            ).scalar_one()
            product_locked.set()
            if not release_locks.wait(timeout=20):
                raise TimeoutError("pre-lock smoke did not release image/product locks")
            db.rollback()

    def submit_unauthorized_direct_id_requests() -> None:
        if not image_locked.wait(timeout=10) or not product_locked.wait(timeout=10):
            raise TimeoutError("could not acquire both source-image and product locks")
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app) as client:
            reviewed = client.post(
                f"/api/v1/shelf-image-detections/{detection_id}/reviews",
                json={"decision": "REJECTED", "notes": "Cross-store pre-lock smoke"},
                headers=headers,
            )
            history = client.get(
                f"/api/v1/shelf-image-detections/{detection_id}/reviews",
                headers=headers,
            )
            exemplar_review = client.patch(
                f"/api/v1/product-embedding-exemplars/{exemplar_id}/review",
                json={
                    "review_status": "REJECTED",
                    "review_notes": "Cross-store pre-lock smoke",
                },
                headers=headers,
            )
        results.update(
            detection_review=reviewed.status_code,
            detection_history=history.status_code,
            exemplar_review=exemplar_review.status_code,
        )

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(update={"app_env": "production"})
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            lock_future = executor.submit(hold_source_and_catalogue_locks)
            try:
                assert image_locked.wait(timeout=10), "source image lock was not acquired"
                assert product_locked.wait(timeout=10), "catalogue product lock was not acquired"
                request_future = executor.submit(submit_unauthorized_direct_id_requests)
                try:
                    request_future.result(timeout=3)
                except TimeoutError as exc:
                    raise AssertionError(
                        "a cross-store detection/exemplar request waited for a locked row "
                        "instead of rejecting before lock acquisition"
                    ) from exc
                assert results == {
                    "detection_review": 403,
                    "detection_history": 403,
                    "exemplar_review": 403,
                }, results
            finally:
                release_locks.set()
            lock_future.result(timeout=10)

        with SessionLocal() as db:
            assert db.query(models.DetectionSkuReview).filter(
                models.DetectionSkuReview.detection_id == detection_id
            ).count() == 0
            exemplar = db.get(models.ProductEmbeddingExemplar, exemplar_id)
            assert exemplar is not None
            assert exemplar.review_status == "PENDING"
            assert exemplar.reviewed_at is None
    finally:
        release_locks.set()
        main_module.settings = original_settings

    print(
        "PostgreSQL direct-ID tenant pre-lock smoke passed: detection review, "
        "review history and exemplar review all returned HTTP 403 while both "
        "source-image and product rows were locked; no review was persisted."
    )


if __name__ == "__main__":
    main()
