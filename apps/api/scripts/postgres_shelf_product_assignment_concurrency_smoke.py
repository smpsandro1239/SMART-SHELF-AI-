"""Exercise concurrent duplicate shelf/product assignments against PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app


def main() -> None:
    suffix = uuid4().hex[:12]
    db = SessionLocal()
    try:
        store = models.Store(code=f"SHELF-RACE-{suffix}", name="Shelf assignment race")
        db.add(store)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Race zone")
        product = models.Product(sku=f"SHELF-RACE-SKU-{suffix}", name="Race product")
        db.add_all([zone, product])
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"RACE-{suffix}")
        db.add(shelf)
        db.commit()
        store_id, shelf_id, product_id = store.id, shelf.id, product.id
    finally:
        db.close()

    original_settings = main_module.settings
    original_request_user = main_module._request_user
    actor = type(
        "Actor",
        (),
        {"id": None, "role": "ADMIN", "store_id": None},
    )()
    main_module.settings = original_settings.model_copy(update={"app_env": "test"})
    main_module._request_user = lambda db, request: actor

    try:
        with TestClient(app) as client:
            barrier = Barrier(2)

            def submit():
                barrier.wait(timeout=10)
                return client.post(
                    "/api/v1/shelf-products",
                    json={
                        "shelf_id": shelf_id,
                        "product_id": product_id,
                        "target_quantity": 8,
                        "min_display_quantity": 2,
                    },
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(lambda _: submit(), range(2)))

        created = [response for response in responses if response.status_code == 201]
        conflicts = [response for response in responses if response.status_code == 409]
        assert len(created) == 1, [
            (response.status_code, response.text) for response in responses
        ]
        assert len(conflicts) == 1, [
            (response.status_code, response.text) for response in responses
        ]

        verify_db = SessionLocal()
        try:
            persisted = (
                verify_db.query(models.ShelfProduct)
                .filter_by(shelf_id=shelf_id, product_id=product_id)
                .count()
            )
            assert persisted == 1, (store_id, shelf_id, product_id, persisted)
        finally:
            verify_db.close()
    finally:
        main_module._request_user = original_request_user
        main_module.settings = original_settings

    print(
        "PostgreSQL concurrent shelf assignment smoke passed: one request "
        "created the association, the competing request received 409, "
        "and exactly one row persisted."
    )


if __name__ == "__main__":
    main()
