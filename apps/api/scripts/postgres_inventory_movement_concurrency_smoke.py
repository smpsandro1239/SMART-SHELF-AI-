"""Prove concurrent reconciliations cannot overdraw one WMS snapshot in PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token


def main() -> None:
    suffix = uuid4().hex[:10]
    with TestClient(app) as client:
        store = client.post(
            "/api/v1/stores",
            json={"code": f"PG-MOVECON-{suffix}", "name": "Movement concurrency smoke"},
        )
        assert store.status_code == 201, store.text
        store_id = store.json()["id"]

        zone = client.post(
            "/api/v1/zones",
            json={"store_id": store_id, "name": "Movement concurrency zone"},
        )
        assert zone.status_code == 201, zone.text

        shelves = []
        for suffix_part in ("A", "B"):
            shelf = client.post(
                "/api/v1/shelves",
                json={"zone_id": zone.json()["id"], "code": f"PG-MOVECON-{suffix}-{suffix_part}"},
            )
            assert shelf.status_code == 201, shelf.text
            shelves.append(shelf.json()["id"])

        product = client.post(
            "/api/v1/products",
            json={"sku": f"PG-MOVECON-SKU-{suffix}", "name": "Concurrency test product"},
        )
        assert product.status_code == 201, product.text
        product_id = product.json()["id"]

        for shelf_id in shelves:
            assignment = client.post(
                "/api/v1/shelf-products",
                json={
                    "shelf_id": shelf_id,
                    "product_id": product_id,
                    "target_quantity": 10,
                    "min_display_quantity": 1,
                },
            )
            assert assignment.status_code == 201, assignment.text

        with SessionLocal() as db:
            db.add(models.InventoryFreshnessPolicy(
                store_id=store_id,
                source="WMS",
                max_age_minutes=240,
                backroom_location_code="BACKROOM-CONCURRENCY",
            ))
            db.commit()

        snapshot = client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_id,
                "product_id": product_id,
                "on_hand_quantity": 7,
                "reserved_quantity": 1,
                "source": "WMS",
                "external_reference": f"PG-MOVECON-SOURCE-{suffix}",
                "location_code": "BACKROOM-CONCURRENCY",
                "availability_status": "AVAILABLE",
            },
        )
        assert snapshot.status_code == 201, snapshot.text
        source_snapshot_id = snapshot.json()["id"]

        task_ids = []
        for shelf_id in shelves:
            task = client.post(
                "/api/v1/tasks",
                json={
                    "store_id": store_id,
                    "shelf_id": shelf_id,
                    "product_id": product_id,
                    "requested_quantity": 4,
                },
            )
            assert task.status_code == 201, task.text
            task_ids.append(task.json()["id"])

        for task_id in task_ids:
            for payload in (
                {"status": "ASSIGNED", "assigned_to": "CI operator"},
                {"status": "IN_PROGRESS"},
                {"status": "COMPLETED", "actual_quantity": 4},
            ):
                response = client.patch(f"/api/v1/tasks/{task_id}/status", json=payload)
                assert response.status_code == 200, response.text

        with SessionLocal() as db:
            actor = models.User(
                email=f"pg-move-concurrency-{suffix}@example.test",
                full_name="Movement concurrency smoke supervisor",
                password_hash="smoke-test-only",
                role="SUPERVISOR",
                store_id=store_id,
                is_active=True,
            )
            db.add(actor)
            db.commit()
            actor_id = actor.id

        token = create_access_token(user_id=actor_id, role="SUPERVISOR")[0]
        headers = {"Authorization": f"Bearer {token}"}
        original_settings = main_module.settings
        main_module.settings = original_settings.model_copy(update={"app_env": "production"})
        barrier = Barrier(2)

        def reconcile(task_id: int):
            barrier.wait(timeout=15)
            return client.post(
                f"/api/v1/tasks/{task_id}/reconcile-inventory",
                json={"reason": "PostgreSQL concurrent stock conservation smoke"},
                headers=headers,
            )

        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(reconcile, task_id) for task_id in task_ids]
                responses = [future.result(timeout=45) for future in futures]
            successful_movement_id = next(
                response.json()["id"] for response in responses if response.status_code == 201
            )
            successful_task_id = next(
                response.json()["task_id"] for response in responses if response.status_code == 201
            )
            retry = client.post(
                f"/api/v1/tasks/{successful_task_id}/reconcile-inventory",
                json={"reason": "PostgreSQL concurrent stock conservation smoke"},
                headers=headers,
            )
        finally:
            main_module.settings = original_settings

        successes = [response for response in responses if response.status_code == 201]
        conflicts = [response for response in responses if response.status_code == 409]
        assert len(successes) == 1, [(r.status_code, r.text) for r in responses]
        assert len(conflicts) == 1, [(r.status_code, r.text) for r in responses]
        conflict_body = conflicts[0].json()
        assert conflict_body.get("detail", {}).get("code") == "INSUFFICIENT_BACKROOM_STOCK", conflict_body
        assert conflict_body["detail"]["available_quantity"] == 2
        assert conflict_body["detail"]["requested_quantity"] == 4

        movement = successes[0].json()
        assert movement["id"] == successful_movement_id
        assert movement["source_snapshot_id"] == source_snapshot_id
        assert movement["quantity"] == 4
        assert retry.status_code == 409, retry.text
        assert retry.json().get("detail", {}).get("code") == "INVENTORY_ALREADY_RECONCILED"
        assert retry.json()["detail"]["movement_id"] == movement["id"]

        with SessionLocal() as db:
            movement_count = db.query(func.count(models.InventoryMovement.id)).filter(
                models.InventoryMovement.source_snapshot_id == source_snapshot_id,
            ).scalar()
            event_count = db.query(func.count(models.InventoryMovementEvent.id)).filter(
                models.InventoryMovementEvent.movement_id == movement["id"],
            ).scalar()
            result_snapshot = db.query(models.InventorySnapshot).filter(
                models.InventorySnapshot.source == "MANUAL",
                models.InventorySnapshot.external_reference == f"TASK-RECONCILIATION-{movement['task_id']}",
            ).one_or_none()
            result_snapshot_count = int(result_snapshot is not None)
            reconciled_task_event_count = db.query(func.count(models.ReplenishmentTaskEvent.id)).filter(
                models.ReplenishmentTaskEvent.event_type == "INVENTORY_RECONCILED",
                models.ReplenishmentTaskEvent.task_id.in_(task_ids),
            ).scalar()

        assert movement_count == 1, movement_count
        assert event_count == 1, event_count
        assert result_snapshot_count == 1, result_snapshot_count
        assert float(result_snapshot.on_hand_quantity) == 3
        assert float(result_snapshot.reserved_quantity) == 1
        assert reconciled_task_event_count == 1, reconciled_task_event_count

    with TestClient(app) as rollback_client:
        rollback_product = rollback_client.post(
            "/api/v1/products",
            json={"sku": f"PG-MOVECON-ROLLBACK-{suffix}", "name": "Rollback test product"},
        )
        assert rollback_product.status_code == 201, rollback_product.text
        rollback_product_id = rollback_product.json()["id"]
        rollback_shelf = rollback_client.post(
            "/api/v1/shelves",
            json={"zone_id": zone.json()["id"], "code": f"PG-MOVECON-{suffix}-ROLLBACK"},
        )
        assert rollback_shelf.status_code == 201, rollback_shelf.text
        rollback_assignment = rollback_client.post(
            "/api/v1/shelf-products",
            json={
                "shelf_id": rollback_shelf.json()["id"],
                "product_id": rollback_product_id,
                "target_quantity": 5,
                "min_display_quantity": 1,
            },
        )
        assert rollback_assignment.status_code == 201, rollback_assignment.text
        rollback_snapshot = rollback_client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_id,
                "product_id": rollback_product_id,
                "on_hand_quantity": 5,
                "reserved_quantity": 1,
                "source": "WMS",
                "external_reference": f"PG-MOVECON-ROLLBACK-SOURCE-{suffix}",
                "location_code": "BACKROOM-CONCURRENCY",
                "availability_status": "AVAILABLE",
            },
        )
        assert rollback_snapshot.status_code == 201, rollback_snapshot.text
        rollback_task = rollback_client.post(
            "/api/v1/tasks",
            json={
                "store_id": store_id,
                "shelf_id": rollback_shelf.json()["id"],
                "product_id": rollback_product_id,
                "requested_quantity": 2,
            },
        )
        assert rollback_task.status_code == 201, rollback_task.text
        rollback_task_id = rollback_task.json()["id"]
        for payload in (
            {"status": "ASSIGNED", "assigned_to": "CI operator"},
            {"status": "IN_PROGRESS"},
            {"status": "COMPLETED", "actual_quantity": 2},
        ):
            response = rollback_client.patch(f"/api/v1/tasks/{rollback_task_id}/status", json=payload)
            assert response.status_code == 200, response.text
    
        with SessionLocal() as db:
            db.connection().exec_driver_sql("""
                CREATE OR REPLACE FUNCTION fail_inventory_movement_event_insert_smoke()
                RETURNS trigger LANGUAGE plpgsql AS $function$
                BEGIN
                    RAISE EXCEPTION 'forced movement event failure' USING ERRCODE = '23514';
                END;
                $function$
            """)
            db.connection().exec_driver_sql("""
                CREATE TRIGGER trg_fail_inventory_movement_event_insert_smoke
                BEFORE INSERT ON inventory_movement_events
                FOR EACH ROW EXECUTE FUNCTION fail_inventory_movement_event_insert_smoke()
            """)
            db.commit()
    
        original_settings = main_module.settings
        main_module.settings = original_settings.model_copy(update={"app_env": "production"})
        try:
            rollback_response = rollback_client.post(
                f"/api/v1/tasks/{rollback_task_id}/reconcile-inventory",
                json={"reason": "PostgreSQL movement event rollback smoke"},
                headers=headers,
            )
        finally:
            main_module.settings = original_settings
            with SessionLocal() as db:
                db.connection().exec_driver_sql(
                    "DROP TRIGGER IF EXISTS trg_fail_inventory_movement_event_insert_smoke ON inventory_movement_events"
                )
                db.connection().exec_driver_sql(
                    "DROP FUNCTION IF EXISTS fail_inventory_movement_event_insert_smoke()"
                )
                db.commit()
    
        assert rollback_response.status_code == 409, rollback_response.text
    assert rollback_response.json().get("detail", {}).get("code") == "INVENTORY_RECONCILIATION_CONFLICT"
    with SessionLocal() as db:
        assert db.query(models.InventoryMovement).filter_by(task_id=rollback_task_id).count() == 0
        preserved_event_count = db.query(models.InventoryMovementEvent).filter_by(
            movement_id=movement["id"],
        ).count()
        assert preserved_event_count == 1, {
            "movement_id": movement["id"],
            "preserved_event_count": preserved_event_count,
        }
        assert db.query(models.InventorySnapshot).filter_by(
            external_reference=f"TASK-RECONCILIATION-{rollback_task_id}",
        ).count() == 0
        assert db.query(models.ReplenishmentTaskEvent).filter_by(
            task_id=rollback_task_id,
            event_type="INVENTORY_RECONCILED",
        ).count() == 0

    print(
        "PostgreSQL inventory movement smoke passed: concurrent reconciliations preserved "
        "reservations and prevented overdraw; retry was idempotent; forced event failure "
        "rolled back the movement, result snapshot and task audit."
    )


if __name__ == "__main__":
    main()
