"""Prove PostgreSQL row-lock serialization between SKU matching and image retention.

The worker locks the target image and approved exemplar source images in one
ascending-ID pass. The retention endpoint uses SELECT FOR UPDATE on the same
shelf_images row. This smoke test uses two independent PostgreSQL sessions and
checks pg_stat_activity to prove the retention transaction is actually blocked
by the matching transaction before allowing matching to commit.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from sqlalchemy import text

from app import models
from app.database import SessionLocal
from app.product_embedding_service import (
    build_approved_product_registry,
    lock_matching_source_images,
)


def _create_fixture(suffix: str) -> tuple[int, int, int]:
    db = SessionLocal()
    try:
        store = models.Store(
            code=f"PG-EMBED-LOCK-{suffix}",
            name="PostgreSQL embedding retention smoke",
        )
        product = models.Product(
            sku=f"PG-EMBED-SKU-{suffix}",
            name="PostgreSQL embedding reference",
        )
        reviewer = models.User(
            email=f"pg-embed-reviewer-{suffix}@example.test",
            full_name="PostgreSQL embedding reviewer",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        db.add_all([store, product, reviewer])
        db.flush()

        zone = models.Zone(store_id=store.id, name="Smoke zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"PG-EMBED-{suffix}")
        db.add(shelf)
        db.flush()

        source_image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="approved-reference.jpg",
            storage_path=f"/tmp/pg-embed-source-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="a" * 64,
            retention_status="ACTIVE",
        )
        target_image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="worker-target.jpg",
            storage_path=f"/tmp/pg-embed-target-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="b" * 64,
            retention_status="ACTIVE",
        )
        db.add_all([source_image, target_image])
        db.flush()

        db.add(models.ProductEmbeddingExemplar(
            product_id=product.id,
            shelf_image_id=source_image.id,
            embedding=[1.0, 0.0, 0.0],
            embedding_dimension=3,
            model_version="pg-embedding-lock-v1",
            image_sha256="a" * 64,
            licence="store-owned-smoke-reference",
            review_status="APPROVED",
            reviewed_by_user_id=reviewer.id,
            reviewed_at=models.utc_now(),
        ))
        db.commit()
        return source_image.id, target_image.id, product.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    suffix = uuid4().hex[:8]
    source_image_id, target_image_id, _product_id = _create_fixture(suffix)
    application_name = f"ss-retention-{suffix}"
    matching_locked = Event()
    allow_matching_commit = Event()
    retention_started = Event()
    retention_finished = Event()

    def matching_transaction() -> None:
        with SessionLocal() as db:
            lock_matching_source_images(
                db,
                target_image_id=target_image_id,
                model_versions={"pg-embedding-lock-v1"},
            )
            matching_locked.set()
            if not allow_matching_commit.wait(timeout=15):
                raise TimeoutError("matching transaction was not released")
            db.commit()

    def retention_transaction() -> None:
        with SessionLocal() as db:
            db.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": application_name},
            )
            retention_started.set()
            image = (
                db.query(models.ShelfImage)
                .filter(models.ShelfImage.id == source_image_id)
                .with_for_update()
                .one()
            )
            image.retention_status = "RESTRICTED"
            image.retention_reason = "PostgreSQL lock serialization smoke"
            image.retention_requested_at = models.utc_now()
            db.commit()
            retention_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        matching_future = executor.submit(matching_transaction)
        assert matching_locked.wait(timeout=10), "matching did not acquire source-image locks"
        retention_future = executor.submit(retention_transaction)
        assert retention_started.wait(timeout=10), "retention transaction did not start"

        deadline = monotonic() + 10
        observed_blocker = False
        while monotonic() < deadline:
            with SessionLocal() as monitor:
                activity = monitor.execute(
                    text(
                        "SELECT wait_event_type, pg_blocking_pids(pid) "
                        "FROM pg_stat_activity WHERE application_name = :name"
                    ),
                    {"name": application_name},
                ).first()
            if activity is not None and activity[0] == "Lock" and activity[1]:
                observed_blocker = True
                break
            if retention_finished.is_set():
                break
            sleep(0.05)

        try:
            assert observed_blocker, (
                "retention did not appear as a PostgreSQL lock waiter blocked "
                "by the matching transaction"
            )
            assert not retention_finished.is_set(), (
                "retention completed before matching released its source-image lock"
            )
        finally:
            allow_matching_commit.set()

        matching_future.result(timeout=10)
        retention_future.result(timeout=10)

    assert retention_finished.is_set(), "retention did not complete after matching commit"

    with SessionLocal() as db:
        source_image = db.get(models.ShelfImage, source_image_id)
        assert source_image is not None
        assert source_image.retention_status == "RESTRICTED"
        registry = build_approved_product_registry(
            db,
            model_version="pg-embedding-lock-v1",
        )
        result = registry.match([1.0, 0.0, 0.0])
        assert result.status == "UNKNOWN", result

    print(
        "PostgreSQL embedding-retention concurrency smoke passed: "
        "retention was observed waiting on the matching row lock, "
        "completed after matching committed, and the restricted exemplar "
        "was excluded from the next registry."
    )


if __name__ == "__main__":
    main()
