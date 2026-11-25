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

        with SessionLocal() as db:
            db.add(models.InventoryFreshnessPolicy(
                store_id=store_id,
                source="WMS",
                max_age_minutes=240,
                backroom_location_code="BACKROOM-CI",
            ))
            db.commit()

        snapshot = client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_id,
                "product_id": product_id,
                "on_hand_quantity": 20,
                "reserved_quantity": 2,
                "source": "WMS",
                "external_reference": f"PG-MOVE-SOURCE-{suffix}",
                "location_code": "BACKROOM-CI",
                "availability_status": "AVAILABLE",
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
            assert reconciled.status_code == 201, reconciled.text
            movement = reconciled.json()
            event_response = client.get(
                f"/api/v1/inventory/movements/{movement['id']}/events",
                headers=headers,
            )
        finally:
            main_module.settings = original_settings
        assert movement["source_snapshot_id"] == source_snapshot_id
        assert movement["destination_shelf_code"] == shelf.json()["code"]
        assert movement["destination_zone_id"] == zone.json()["id"]
        assert movement["destination_zone_name"] == zone.json()["name"]
        assert movement["destination_location_backfilled"] is False
        assert movement["quantity"] == 4
        assert event_response.status_code == 200, event_response.text
        assert len(event_response.json()) == 1
        recorded_event = event_response.json()[0]
        assert recorded_event["event_type"] == "MOVEMENT_RECORDED"
        assert recorded_event["operation_id"] == movement["operation_id"]
        assert recorded_event["actor_user_id"] == supervisor_id
        assert recorded_event["evidence"]["source_snapshot_id"] == source_snapshot_id
        assert recorded_event["evidence"]["destination_shelf_code"] == shelf.json()["code"]
        assert recorded_event["evidence"]["destination_zone_id"] == zone.json()["id"]
        assert recorded_event["evidence"]["destination_zone_name"] == zone.json()["name"]
        assert recorded_event["evidence"]["destination_location_backfilled"] is False

    with SessionLocal() as db:
        external_actor = models.User(
            email=f"pg-movement-external-{suffix}@example.test",
            full_name="Movement event integration actor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store_id,
            is_active=True,
        )
        db.add(external_actor)
        db.commit()
        external_actor_id = external_actor.id

        # Future WMS events may have their own actor/reason, but must retain the
        # exact movement operation and tenant identity.
        db.execute(text("""
            INSERT INTO inventory_movement_events
                (movement_id, operation_id, store_id, event_type, actor_user_id, reason, evidence, created_at)
            VALUES (:movement_id, :operation_id, :store_id, 'WMS_CONFIRMATION_RECORDED',
                    :actor_id, 'Synthetic confirmation event for database smoke', '{}'::json, CURRENT_TIMESTAMP)
        """), {
            "movement_id": movement["id"],
            "operation_id": movement["operation_id"],
            "store_id": store_id,
            "actor_id": external_actor_id,
        })
        db.commit()

        try:
            db.execute(text("""
                INSERT INTO inventory_movement_events
                    (movement_id, operation_id, store_id, event_type, actor_user_id, reason, evidence, created_at)
                VALUES (:movement_id, :operation_id, :store_id, 'COMPENSATION_RECORDED',
                        :actor_id, 'Mismatched operation smoke', '{}'::json, CURRENT_TIMESTAMP)
            """), {
                "movement_id": movement["id"],
                "operation_id": str(uuid4()),
                "store_id": store_id,
                "actor_id": external_actor_id,
            })
            db.commit()
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL accepted a movement event with a mismatched operation_id")

        movement_event_count = db.execute(
            text("SELECT COUNT(*) FROM inventory_movement_events WHERE movement_id = :movement_id"),
            {"movement_id": movement["id"]},
        ).scalar_one()
        assert movement_event_count == 2, movement_event_count

        event_id = db.execute(
            text("SELECT id FROM inventory_movement_events WHERE movement_id = :movement_id ORDER BY id LIMIT 1"),
            {"movement_id": movement["id"]},
        ).scalar_one()
        for statement in (
            "UPDATE inventory_movement_events SET reason = 'tampered' WHERE id = :event_id",
            "DELETE FROM inventory_movement_events WHERE id = :event_id",
        ):
            try:
                db.execute(text(statement), {"event_id": event_id})
                db.commit()
            except DBAPIError:
                db.rollback()
            else:
                raise AssertionError("PostgreSQL allowed an inventory movement event mutation")

        movement_event_count = db.execute(
            text("SELECT COUNT(*) FROM inventory_movement_events WHERE movement_id = :movement_id"),
            {"movement_id": movement["id"]},
        ).scalar_one()
        assert movement_event_count == 2, movement_event_count

        invalid_inserts = (
            {
                "store_id": store_id + 100000,
                "product_id": product_id,
                "quantity": 4,
                "unit_code": "un",
                "result_snapshot_id": movement["result_snapshot_id"],
                "destination_shelf_id": shelf.json()["id"] + 100000,
                "destination_shelf_code": shelf.json()["code"],
                "destination_zone_id": zone.json()["id"],
                "destination_zone_name": zone.json()["name"],
                "destination_location_backfilled": False,
            },
            {
                "store_id": store_id,
                "product_id": product_id,
                "quantity": 4,
                "unit_code": "un",
                "result_snapshot_id": movement["result_snapshot_id"],
                "destination_shelf_id": shelf.json()["id"],
                "destination_shelf_code": "FORGED-SHELF-CODE",
                "destination_zone_id": zone.json()["id"],
                "destination_zone_name": zone.json()["name"],
                "destination_location_backfilled": False,
            },
            {
                "store_id": store_id,
                "product_id": product_id,
                "quantity": 4,
                "unit_code": "un",
                "result_snapshot_id": movement["result_snapshot_id"],
                "destination_shelf_id": shelf.json()["id"],
                "destination_shelf_code": shelf.json()["code"],
                "destination_zone_id": zone.json()["id"],
                "destination_zone_name": "Forged zone name",
                "destination_location_backfilled": False,
            },
            {
                "store_id": store_id,
                "product_id": product_id,
                "quantity": 4,
                "unit_code": "un",
                "result_snapshot_id": movement["result_snapshot_id"],
                "destination_shelf_id": shelf.json()["id"],
                "destination_shelf_code": shelf.json()["code"],
                "destination_zone_id": zone.json()["id"],
                "destination_zone_name": zone.json()["name"],
                "destination_location_backfilled": True,
            },
        )
        for values in invalid_inserts:
            try:
                db.execute(
                    text(
                        """
                        INSERT INTO inventory_movements
                            (task_id, store_id, product_id, movement_type, quantity,
                             unit_code, source_snapshot_id, destination_shelf_id,
                             destination_shelf_code, destination_zone_id, destination_zone_name,
                             destination_location_backfilled, result_snapshot_id, actor_user_id, reason, created_at)
                        VALUES
                            (:task_id, :store_id, :product_id, 'BACKROOM_TO_SHELF',
                             :quantity, :unit_code, :source_id, :destination_shelf_id,
                             :destination_shelf_code, :destination_zone_id, :destination_zone_name,
                             :destination_location_backfilled, :result_id, :actor_id,
                             'invalid lineage smoke', CURRENT_TIMESTAMP)
                        """
                    ),
                    {
                        "task_id": task_id,
                        "store_id": values["store_id"],
                        "product_id": values["product_id"],
                        "quantity": values["quantity"],
                        "unit_code": values["unit_code"],
                        "source_id": source_snapshot_id,
                        "destination_shelf_id": values["destination_shelf_id"],
                        "destination_shelf_code": values["destination_shelf_code"],
                        "destination_zone_id": values["destination_zone_id"],
                        "destination_zone_name": values["destination_zone_name"],
                        "destination_location_backfilled": values["destination_location_backfilled"],
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
            "UPDATE inventory_movements SET destination_zone_name = 'Zona adulterada' WHERE task_id = :task_id",
            "UPDATE inventory_movements SET destination_zone_id = destination_zone_id + 100000 WHERE task_id = :task_id",
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

    with TestClient(app) as unavailable_client:
        unavailable_snapshot = unavailable_client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_id,
                "product_id": product_id,
                "on_hand_quantity": 20,
                "reserved_quantity": 2,
                "source": "WMS",
                "external_reference": f"PG-MOVE-UNAVAILABLE-{suffix}",
                "location_code": "BACKROOM-CI",
                "availability_status": "UNAVAILABLE",
            },
        )
        assert unavailable_snapshot.status_code == 201, unavailable_snapshot.text
        available_snapshot = unavailable_client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_id,
                "product_id": product_id,
                "on_hand_quantity": 20,
                "reserved_quantity": 2,
                "source": "WMS",
                "external_reference": f"PG-MOVE-AVAILABLE-UNIT-{suffix}",
                "location_code": "BACKROOM-CI",
                "availability_status": "AVAILABLE",
            },
        )
        assert available_snapshot.status_code == 201, available_snapshot.text
        unavailable_task = unavailable_client.post(
            "/api/v1/tasks",
            json={
                "store_id": store_id,
                "shelf_id": shelf.json()["id"],
                "product_id": product_id,
                "requested_quantity": 4,
            },
        )
        assert unavailable_task.status_code == 201, unavailable_task.text
        unavailable_task_id = unavailable_task.json()["id"]
        for payload in (
            {"status": "ASSIGNED", "assigned_to": "CI operator"},
            {"status": "IN_PROGRESS"},
            {"status": "COMPLETED", "actual_quantity": 4},
        ):
            response = unavailable_client.patch(
                f"/api/v1/tasks/{unavailable_task_id}/status",
                json=payload,
            )
            assert response.status_code == 200, response.text

    with SessionLocal() as db:
        now = models.utc_now()
        result = models.InventorySnapshot(
            store_id=store_id,
            product_id=product_id,
            on_hand_quantity=16,
            reserved_quantity=2,
            source="MANUAL",
            external_reference=f"TASK-RECONCILIATION-{unavailable_task_id}",
            captured_at=now,
            created_at=now,
        )
        db.add(result)
        db.commit()
        result_snapshot_id = result.id

        try:
            db.execute(text("""
                INSERT INTO inventory_movements
                    (task_id, store_id, product_id, movement_type, quantity, unit_code,
                     source_snapshot_id, source_location_code, destination_shelf_id,
                     destination_shelf_code, destination_zone_id, destination_zone_name,
                     result_snapshot_id, actor_user_id, reason, operation_id, created_at)
                VALUES
                    (:task_id, :store_id, :product_id, 'BACKROOM_TO_SHELF', 4, 'un',
                     :source_snapshot_id, 'BACKROOM-CI', :destination_shelf_id,
                     :destination_shelf_code, :destination_zone_id, :destination_zone_name,
                     :result_snapshot_id, :actor_id, 'unavailable source guard smoke',
                     :operation_id, CURRENT_TIMESTAMP)
            """), {
                "task_id": unavailable_task_id,
                "store_id": store_id,
                "product_id": product_id,
                "source_snapshot_id": unavailable_snapshot.json()["id"],
                "destination_shelf_id": shelf.json()["id"],
                "destination_shelf_code": shelf.json()["code"],
                "destination_zone_id": zone.json()["id"],
                "destination_zone_name": zone.json()["name"],
                "result_snapshot_id": result_snapshot_id,
                "actor_id": supervisor_id,
                "operation_id": str(uuid4()),
            })
            db.commit()
        except DBAPIError as exc:
            db.rollback()
            assert "same-store physical provenance" in str(exc.orig), str(exc.orig)
        else:
            raise AssertionError("PostgreSQL accepted a movement from an UNAVAILABLE WMS snapshot")

        try:
            db.execute(text("""
                INSERT INTO inventory_movements
                    (task_id, store_id, product_id, movement_type, quantity, unit_code,
                     source_snapshot_id, source_location_code, destination_shelf_id,
                     destination_shelf_code, destination_zone_id, destination_zone_name,
                     result_snapshot_id, actor_user_id, reason, operation_id, created_at)
                VALUES
                    (:task_id, :store_id, :product_id, 'BACKROOM_TO_SHELF', 4, 'kg',
                     :source_snapshot_id, 'BACKROOM-CI', :destination_shelf_id,
                     :destination_shelf_code, :destination_zone_id, :destination_zone_name,
                     :result_snapshot_id, :actor_id, 'wrong base unit smoke',
                     :operation_id, CURRENT_TIMESTAMP)
            """), {
                "task_id": unavailable_task_id,
                "store_id": store_id,
                "product_id": product_id,
                "source_snapshot_id": available_snapshot.json()["id"],
                "destination_shelf_id": shelf.json()["id"],
                "destination_shelf_code": shelf.json()["code"],
                "destination_zone_id": zone.json()["id"],
                "destination_zone_name": zone.json()["name"],
                "result_snapshot_id": result_snapshot_id,
                "actor_id": supervisor_id,
                "operation_id": str(uuid4()),
            })
            db.commit()
        except DBAPIError as exc:
            db.rollback()
            assert "match the product base unit" in str(exc.orig), str(exc.orig)
        else:
            raise AssertionError("PostgreSQL accepted a movement with a non-product base unit")

        unavailable_movement_count = db.execute(
            text("SELECT COUNT(*) FROM inventory_movements WHERE task_id = :task_id"),
            {"task_id": unavailable_task_id},
        ).scalar_one()
        assert unavailable_movement_count == 0, unavailable_movement_count

    with SessionLocal() as db:
        renamed_shelf_code = f"RENAMED-{suffix}"
        renamed_zone_name = f"Renamed zone {suffix}"
        db.execute(
            text("UPDATE shelves SET code = :code WHERE id = :shelf_id"),
            {"code": renamed_shelf_code, "shelf_id": shelf.json()["id"]},
        )
        db.execute(
            text("UPDATE zones SET name = :name WHERE id = :zone_id"),
            {"name": renamed_zone_name, "zone_id": zone.json()["id"]},
        )
        db.commit()
        frozen = db.execute(text("""
            SELECT destination_shelf_code, destination_zone_id,
                   destination_zone_name, destination_location_backfilled
            FROM inventory_movements WHERE id = :movement_id
        """), {"movement_id": movement["id"]}).one()
        assert frozen == (
            shelf.json()["code"], zone.json()["id"], zone.json()["name"], False,
        ), frozen
        for statement, parameters in (
            ("DELETE FROM shelves WHERE id = :id", {"id": shelf.json()["id"]}),
            ("DELETE FROM zones WHERE id = :id", {"id": zone.json()["id"]}),
        ):
            try:
                db.execute(text(statement), parameters)
                db.commit()
            except DBAPIError:
                db.rollback()
            else:
                raise AssertionError("PostgreSQL allowed deletion of a shelf/zone referenced by an immutable movement")

    with TestClient(app) as retention_client:
        retention_zone = retention_client.post("/api/v1/zones", json={
            "store_id": store_id, "name": f"Task retention zone {suffix}",
        })
        assert retention_zone.status_code == 201, retention_zone.text
        retention_shelf = retention_client.post("/api/v1/shelves", json={
            "zone_id": retention_zone.json()["id"], "code": f"TASK-RETENTION-{suffix}",
        })
        assert retention_shelf.status_code == 201, retention_shelf.text
        assignment = retention_client.post("/api/v1/shelf-products", json={
            "shelf_id": retention_shelf.json()["id"], "product_id": product_id,
            "target_quantity": 10, "min_display_quantity": 1,
        })
        assert assignment.status_code == 201, assignment.text
        task_without_movement = retention_client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": retention_shelf.json()["id"],
            "product_id": product_id, "requested_quantity": 2,
        })
        assert task_without_movement.status_code == 201, task_without_movement.text

    with SessionLocal() as db:
        task_id_without_movement = task_without_movement.json()["id"]
        task_event_id = db.execute(
            text("SELECT id FROM replenishment_task_events WHERE task_id = :task_id ORDER BY id LIMIT 1"),
            {"task_id": task_id_without_movement},
        ).scalar_one()
        guarded_operations = (
            (
                "UPDATE replenishment_tasks SET shelf_id = :shelf_id WHERE id = :task_id",
                {"shelf_id": shelf.json()["id"], "task_id": task_id_without_movement},
                "replenishment task identity is immutable after audit begins",
            ),
            (
                "DELETE FROM replenishment_tasks WHERE id = :task_id",
                {"task_id": task_id_without_movement},
                "replenishment task has audit history",
            ),
            (
                "UPDATE replenishment_task_events SET reason = 'tampered' WHERE id = :event_id",
                {"event_id": task_event_id},
                "replenishment task events are append-only",
            ),
            (
                "DELETE FROM replenishment_task_events WHERE id = :event_id",
                {"event_id": task_event_id},
                "replenishment task events are append-only",
            ),
        )
        for statement, parameters, expected in guarded_operations:
            try:
                db.execute(text(statement), parameters)
                db.commit()
            except DBAPIError as exc:
                db.rollback()
                assert expected in str(exc.orig), str(exc.orig)
            else:
                raise AssertionError("PostgreSQL allowed task identity/audit history mutation")
        task_event_count = db.execute(
            text("SELECT COUNT(*) FROM replenishment_task_events WHERE task_id = :task_id"),
            {"task_id": task_id_without_movement},
        ).scalar_one()
        assert task_event_count >= 1

        for statement, parameters, expected in (
            ("DELETE FROM shelves WHERE id = :id", {"id": retention_shelf.json()["id"]}, "shelf has retained operational evidence"),
            ("DELETE FROM zones WHERE id = :id", {"id": retention_zone.json()["id"]}, "zone has retained shelf evidence"),
        ):
            try:
                db.execute(text(statement), parameters)
                db.commit()
            except DBAPIError as exc:
                db.rollback()
                assert expected in str(exc.orig), str(exc.orig)
            else:
                raise AssertionError("PostgreSQL deleted a shelf/zone with task history but no movement")
        retained = db.execute(
            text("SELECT COUNT(*) FROM replenishment_tasks WHERE id = :task_id"),
            {"task_id": task_without_movement.json()["id"]},
        ).scalar_one()
        assert retained == 1

    print(
        "PostgreSQL inventory movement smoke passed: immutable movement/shelf/zone provenance, task identity and audit immutability, "
        "retention after hierarchy rename, append-only guards and rejection of UNAVAILABLE WMS sources."
    )


if __name__ == "__main__":
    main()
