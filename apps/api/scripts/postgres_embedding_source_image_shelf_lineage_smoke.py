"""Prove embedding review serializes and protects source-image shelf lineage."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token
from scripts.postgres_embedding_retention_smoke import _create_fixture


def _wait_for_lock_wait(pid: int, label: str, timeout: float = 10) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        with SessionLocal() as monitor:
            row = monitor.execute(
                text(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                ),
                {"pid": pid},
            ).scalar_one_or_none()
        if row == "Lock":
            return
        sleep(0.01)
    raise AssertionError(
        f"{label}: PostgreSQL did not report wait_event_type='Lock' for PID {pid}"
    )


def main() -> None:
    suffix = uuid4().hex[:8]
    source_image_id, _target_image_id, _source_product_id = _create_fixture(suffix)

    db = SessionLocal()
    try:
        source_image = db.get(models.ShelfImage, source_image_id)
        assert source_image is not None
        original_shelf_id = source_image.shelf_id
        creator = db.query(models.User).filter_by(
            email=f"pg-embed-reviewer-{suffix}@example.test"
        ).one()

        target_store = models.Store(
            code=f"PG-EMBED-MOVE-{suffix}",
            name="Embedding source reassignment target",
        )
        target_product = models.Product(
            sku=f"PG-EMBED-MOVE-SKU-{suffix}",
            name="Embedding source reassignment product",
        )
        reviewer = models.User(
            email=f"pg-embed-move-reviewer-{suffix}@example.test",
            full_name="Embedding source move reviewer",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        db.add_all([target_store, target_product, reviewer])
        db.flush()
        target_zone = models.Zone(
            store_id=target_store.id,
            name="Embedding source reassignment zone",
        )
        db.add(target_zone)
        db.flush()
        target_shelf = models.Shelf(
            zone_id=target_zone.id,
            code=f"PG-EMBED-MOVE-{suffix}",
        )
        db.add(target_shelf)
        db.flush()

        exemplar = models.ProductEmbeddingExemplar(
            product_id=target_product.id,
            shelf_image_id=source_image_id,
            embedding=[0.0, 1.0, 0.0],
            embedding_dimension=3,
            model_version="pg-embedding-source-move-v1",
            image_sha256=source_image.sha256,
            licence="store-owned-smoke-reference",
            review_status="PENDING",
            created_by_user_id=creator.id,
        )
        db.add(exemplar)
        db.commit()
        exemplar_id = exemplar.id
        target_product_id = target_product.id
        target_shelf_id = target_shelf.id
        reviewer_id = reviewer.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    token = create_access_token(user_id=reviewer_id, role="ADMIN")[0]
    holder_ready = Event()
    release_product_lock = Event()
    move_started = Event()
    move_finished = Event()
    move_pid: list[int] = []
    move_result: list[str] = []
    application_name = f"ss-embed-image-move-{suffix}"

    def hold_product_lock() -> int:
        with SessionLocal() as lock_db:
            lock_db.execute(
                select(models.Product)
                .where(models.Product.id == target_product_id)
                .with_for_update()
            ).scalar_one()
            backend_pid = lock_db.execute(
                text("SELECT pg_backend_pid()")
            ).scalar_one()
            holder_ready.set()
            if not release_product_lock.wait(timeout=20):
                raise TimeoutError("Timed out holding embedding review product lock")
            lock_db.commit()
            return backend_pid

    def submit_review():
        with TestClient(app) as client:
            return client.patch(
                f"/api/v1/product-embedding-exemplars/{exemplar_id}/review",
                json={
                    "review_status": "APPROVED",
                    "review_notes": "PostgreSQL source-image shelf lineage smoke",
                },
                headers={"Authorization": f"Bearer {token}"},
            )

    def move_source_image():
        with SessionLocal() as move_db:
            move_db.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": application_name},
            )
            move_pid.append(
                move_db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            move_started.set()
            try:
                move_db.execute(
                    text(
                        "UPDATE shelf_images SET shelf_id = :target_shelf_id "
                        "WHERE id = :image_id"
                    ),
                    {
                        "target_shelf_id": target_shelf_id,
                        "image_id": source_image_id,
                    },
                )
                move_db.commit()
                move_result.append("committed")
            except DBAPIError as exc:
                move_db.rollback()
                move_result.append(str(exc.orig))
            finally:
                move_finished.set()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(
        update={"app_env": "production"}
    )
    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            holder_future = executor.submit(hold_product_lock)
            assert holder_ready.wait(timeout=10), "product lock holder did not start"
            holder_pid = holder_future.result(timeout=0.1) if holder_future.done() else None

            review_future = executor.submit(submit_review)

            # The review endpoint locks the source image before it waits on the
            # product row. Observe that exact PostgreSQL lock wait before racing
            # the image reassignment.
            deadline = monotonic() + 10
            review_backend_pid = None
            while monotonic() < deadline:
                with SessionLocal() as monitor:
                    row = monitor.execute(
                        text(
                            """
                            SELECT pid
                            FROM pg_stat_activity
                            WHERE wait_event_type = 'Lock'
                              AND query ILIKE '%product_embedding_exemplars%'
                              AND :holder_pid = ANY(pg_blocking_pids(pid))
                            ORDER BY query_start DESC
                            LIMIT 1
                            """
                        ),
                        {"holder_pid": holder_pid},
                    ).scalar_one_or_none()
                if row is not None:
                    review_backend_pid = row
                    break
                sleep(0.01)
            assert review_backend_pid is not None, (
                "review endpoint did not reach the expected product-row lock wait"
            )

            move_future = executor.submit(move_source_image)
            assert move_started.wait(timeout=10), "source-image move did not start"
            _wait_for_lock_wait(move_pid[0], "concurrent source-image reassignment")

            # Releasing the product lock lets the review commit. The waiting
            # shelf reassignment then reaches migration 0100 and must be denied.
            release_product_lock.set()
            response = review_future.result(timeout=20)
            assert response.status_code == 200, response.text
            assert move_finished.wait(timeout=10), "source-image move did not finish"
            move_future.result(timeout=10)
            holder_future.result(timeout=10)
            assert len(move_result) == 1 and "shelf image shelf cannot change" in move_result[0], (
                f"source-image reassignment was not rejected by the lineage guard: {move_result}"
            )
    finally:
        release_product_lock.set()
        main_module.settings = original_settings

    with SessionLocal() as db:
        image = db.get(models.ShelfImage, source_image_id)
        reviewed = db.get(models.ProductEmbeddingExemplar, exemplar_id)
        assert image is not None and image.shelf_id == original_shelf_id
        assert reviewed is not None and reviewed.review_status == "APPROVED"
        assert reviewed.reviewed_by_user_id == reviewer_id

    print(
        "PostgreSQL embedding source-image lineage smoke passed: the review held "
        "the image lock, the competing shelf reassignment waited on a real "
        "PostgreSQL lock, and migration 0100 rejected the reassignment after "
        "the review committed."
    )


if __name__ == "__main__":
    main()
