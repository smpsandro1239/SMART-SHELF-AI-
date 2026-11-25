"""Prove concurrent SKU-exemplar reviews are serialized on PostgreSQL 16."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token


def main() -> None:
    suffix = uuid4().hex[:8]
    db = SessionLocal()
    try:
        store = models.Store(
            code=f"PG-EMBED-REVIEW-{suffix}",
            name="PostgreSQL embedding review smoke",
        )
        product = models.Product(
            sku=f"PG-EMBED-REVIEW-SKU-{suffix}",
            name="Concurrent review product",
        )
        reviewer_a = models.User(
            email=f"pg-review-a-{suffix}@example.test",
            full_name="PostgreSQL reviewer A",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        reviewer_b = models.User(
            email=f"pg-review-b-{suffix}@example.test",
            full_name="PostgreSQL reviewer B",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        db.add_all([store, product, reviewer_a, reviewer_b])
        db.flush()
        supervisor = models.User(
            email=f"pg-review-supervisor-{suffix}@example.test",
            full_name="PostgreSQL store supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store.id,
            is_active=True,
        )
        db.add(supervisor)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Review smoke zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"PG-REVIEW-{suffix}")
        db.add(shelf)
        db.flush()
        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="review-source.jpg",
            storage_path=f"/tmp/pg-review-source-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="c" * 64,
            retention_status="ACTIVE",
        )
        db.add(image)
        db.flush()
        exemplar = models.ProductEmbeddingExemplar(
            product_id=product.id,
            shelf_image_id=image.id,
            embedding=[1.0, 0.0, 0.0],
            embedding_dimension=3,
            model_version="pg-review-model-v1",
            image_sha256="c" * 64,
            licence="store-owned-smoke-reference",
            review_status="PENDING",
            created_by_user_id=reviewer_a.id,
        )
        db.add(exemplar)
        image_less_exemplar = models.ProductEmbeddingExemplar(
            product_id=product.id,
            shelf_image_id=None,
            embedding=[0.0, 1.0, 0.0],
            embedding_dimension=3,
            model_version="pg-review-model-v1",
            image_sha256="d" * 64,
            licence="store-owned-smoke-reference",
            review_status="PENDING",
            created_by_user_id=reviewer_a.id,
        )
        db.add(image_less_exemplar)
        db.commit()
        exemplar_id = exemplar.id
        image_less_exemplar_id = image_less_exemplar.id
        product_id = product.id
        reviewer_a_id = reviewer_a.id
        reviewer_b_id = reviewer_b.id
        supervisor_id = supervisor.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    tokens = {
        reviewer_a_id: create_access_token(user_id=reviewer_a_id, role="ADMIN")[0],
        reviewer_b_id: create_access_token(user_id=reviewer_b_id, role="ADMIN")[0],
        supervisor_id: create_access_token(user_id=supervisor_id, role="SUPERVISOR")[0],
    }
    barrier = Barrier(2)

    def submit_review(reviewer_id: int, decision: str):
        headers = {"Authorization": f"Bearer {tokens[reviewer_id]}"}
        barrier.wait(timeout=10)
        with TestClient(app) as client:
            response = client.patch(
                f"/api/v1/product-embedding-exemplars/{exemplar_id}/review",
                json={
                    "review_status": decision,
                    "review_notes": f"Concurrent PostgreSQL smoke: {decision}",
                },
                headers=headers,
            )
        return decision, response.status_code, response.json()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(
        update={"app_env": "production"}
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(submit_review, reviewer_a_id, "APPROVED"),
                executor.submit(submit_review, reviewer_b_id, "REJECTED"),
            ]
            results = [future.result(timeout=20) for future in futures]

        successful = [item for item in results if item[1] == 200]
        conflicts = [item for item in results if item[1] == 409]
        assert len(successful) == 1, results
        assert len(conflicts) == 1, results
        winning_decision = successful[0][0]
        assert successful[0][2]["review_status"] == winning_decision

        with SessionLocal() as db:
            stored = db.get(models.ProductEmbeddingExemplar, exemplar_id)
            assert stored is not None
            assert stored.review_status == winning_decision
            expected_reviewer_id = (
                reviewer_a_id if winning_decision == "APPROVED" else reviewer_b_id
            )
            assert stored.reviewed_by_user_id == expected_reviewer_id
            assert stored.reviewed_at is not None

        # A supervisor cannot review a source-less exemplar. Keep its global
        # product row locked and prove the HTTP 403 is returned without waiting.
        from sqlalchemy import select
        from threading import Event

        product_lock_acquired = Event()
        release_product_lock = Event()

        def hold_product_lock():
            with SessionLocal() as lock_db:
                lock_db.execute(
                    select(models.Product)
                    .where(models.Product.id == product_id)
                    .with_for_update()
                ).scalar_one()
                product_lock_acquired.set()
                if not release_product_lock.wait(timeout=10):
                    raise TimeoutError("Timed out holding source-less exemplar product lock")
                lock_db.rollback()

        def reject_source_less_review():
            if not product_lock_acquired.wait(timeout=10):
                raise TimeoutError("Could not acquire source-less exemplar product lock")
            with TestClient(app) as client:
                response = client.patch(
                    f"/api/v1/product-embedding-exemplars/{image_less_exemplar_id}/review",
                    json={
                        "review_status": "REJECTED",
                        "review_notes": "PostgreSQL cross-role pre-lock smoke",
                    },
                    headers={
                        "Authorization": f"Bearer {tokens[supervisor_id]}",
                    },
                )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            lock_future = executor.submit(hold_product_lock)
            if not product_lock_acquired.wait(timeout=10):
                release_product_lock.set()
                raise TimeoutError("Could not acquire product lock for source-less review")
            review_future = executor.submit(reject_source_less_review)
            try:
                status_code = review_future.result(timeout=2)
                assert status_code == 403, status_code
            except TimeoutError as exc:
                raise AssertionError(
                    "Unauthorized source-less exemplar review waited for the product row lock"
                ) from exc
            finally:
                release_product_lock.set()
            lock_future.result(timeout=10)

        with SessionLocal() as db:
            untouched = db.get(models.ProductEmbeddingExemplar, image_less_exemplar_id)
            assert untouched is not None
            assert untouched.review_status == "PENDING"
            assert untouched.reviewed_at is None
    finally:
        main_module.settings = original_settings

    print(
        "PostgreSQL embedding review concurrency smoke passed: "
        "exactly one reviewer committed and the competing decision received HTTP 409."
    )


if __name__ == "__main__":
    main()
