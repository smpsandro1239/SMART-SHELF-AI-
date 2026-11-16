"""Verify PostgreSQL enforces inventory movement lineage at the database boundary."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token


def main() -> None:
    suffix = uuid4().hex[:10]
    with TestClient(app) as client:
        store = client.post(
            "/api/v1/stores",
            json={"code": f"PG-MOVE-{suffix}", "name": "Movement lineage smoke"},
        )
        assert store.status_code == 201, store.text
        store_id = store.json()["id"]

        zone = client.post(
            "/api/v1/zones",
            json={"store_id": store_id, "name": "Movement lineage zone"},
        )
        assert zone.status_code == 201, zone.text
        shelf = client.post(
            "/api/v1/shelves",
            json={"zone_id": zone.json()["id"], "code": f"PG-MOVE-{suffix}"},
        )
        assert shelf.status_code == 201, shelf.text

        product = client.post(
            "/api/v1/products",
            json={"sku": f"PG-MOVE-SKU-{suffix}", "name": "Movement lineage product"},
        )
        assert product.status_code == 201, product.text
        product_id = product.json()["id"]

        assignment = client.post(
            "/api/v1/shelf-products",
            json={
                "shelf_id": shelf.json()["id"],
                "product_id": product_id,
                "target_quantity": 10,
                "min_display_quantity": 1,
            },
        )
        assert assignment.status_code == 201, assignment.text

        snapshot = client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_id,
                "product_id": product_id,
                "on_hand_quantity": 20,
                "reserved_quantity": 2,
                "source": "ERP",
                "external_reference": f"PG-MOVE-SOURCE-{suffix}",
            },
        )
        assert snapshot.status_code == 201, snapshot.text
        source_snapshot_id = snapshot.json()["id"]

        task = client.post(
            "/api/v1/tasks",
            json={
                "store_id": store_id,
                "shelf_id": shelf.json()["id"],
                "product_id": product_id,
                "requested_quantity": 4,
            },
        )
        assert task.status_code == 201, task.text
        task_id = task.json()["id"]

        with SessionLocal() as db:
            supervisor = models.User(
                email=f"pg-movement-supervisor-{suffix}@example.test",
                full_name="Movement lineage smoke supervisor",
                password_hash="smoke-test-only",
                role="SUPERVISOR",
                store_id=store_id,
                is_active=True,
            )
            db.add(supervisor)
            db.commit()
            supervisor_id = supervisor.id

        headers = {
            "Authorization": "Bearer "
            + create_access_token(user_id=supervisor_id, role="SUPERVISOR")[0]
        }
        for status, payload in (
            ("ASSIGNED", {"status": "ASSIGNED", "assigned_to": "CI operator"}),
            ("IN_PROGRESS", {"status": "IN_PROGRESS"}),
            ("COMPLETED", {"status": "COMPLETED", "actual_quantity": 4}),
        ):
            response = client.patch(f"/api/v1/tasks/{task_id}/status", json=payload)
            assert response.status_code == 200, response.text

        original_settings = main_module.settings
        main_module.settings = original_settings.model_copy(update={"app_env": "production"})
        try:
            reconciled = client.post(
                f"/api/v1/tasks/{task_id}/reconcile-inventory",
                json={"reason": "PostgreSQL movement lineage guard smoke"},
                headers=headers,
            )
        finally:
            main_module.settings = original_settings
        assert reconciled.status_code == 201, reconciled.text
        movement = reconciled.json()
        assert movement["source_snapshot_id"] == source_snapshot_id
        assert movement["quantity"] == 4

    with SessionLocal() as db:
        invalid_inserts = (
            {
                "store_id": store_id + 100000,
                "product_id": product_id,
                "quantity": 4,
                "result_snapshot_id": movement["result_snapshot_id"],
            },
            {
                "store_id": store_id,
                "product_id": product_id,
                "quantity": 4,
                "result_snapshot_id": movement["result_snapshot_id"],
            },
        )
        for values in invalid_inserts:
            try:
                db.execute(
                    text(
                        """
                        INSERT INTO inventory_movements
                            (task_id, store_id, product_id, movement_type, quantity,
                             source_snapshot_id, result_snapshot_id, actor_user_id,
                             reason, created_at)
                        VALUES
                            (:task_id, :store_id, :product_id, 'BACKROOM_TO_SHELF',
                             :quantity, :source_id, :result_id, :actor_id,
                             'invalid lineage smoke', CURRENT_TIMESTAMP)
                        """
                    ),
                    {
                        "task_id": task_id,
                        "store_id": values["store_id"],
                        "product_id": values["product_id"],
                        "quantity": values["quantity"],
                        "source_id": source_snapshot_id,
                        "result_id": values["result_snapshot_id"],
                        "actor_id": supervisor_id,
                    },
                )
                db.commit()
            except DBAPIError:
                db.rollback()
            else:
                raise AssertionError(
                    "PostgreSQL accepted an inconsistent inventory movement"
                )

        count = db.execute(
            text("SELECT COUNT(*) FROM inventory_movements WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).scalar_one()
        assert count == 1, count

        for statement in (
            "UPDATE inventory_movements SET quantity = 99 WHERE task_id = :task_id",
            "DELETE FROM inventory_movements WHERE task_id = :task_id",
        ):
            try:
                db.execute(text(statement), {"task_id": task_id})
                db.commit()
            except DBAPIError:
                db.rollback()
            else:
                raise AssertionError(
                    "PostgreSQL allowed an approved inventory movement to be mutated"
                )

        count = db.execute(
            text("SELECT COUNT(*) FROM inventory_movements WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).scalar_one()
        assert count == 1, count

    print(
        "PostgreSQL inventory movement smoke passed: valid reconciliation persisted; "
        "invalid lineage, non-conserving duplicates, UPDATE and DELETE were rejected."
    )


if __name__ == "__main__":
    main()
