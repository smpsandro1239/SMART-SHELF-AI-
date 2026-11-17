"""Verify inventory and warehouse cross-store authorization on PostgreSQL 16.

This smoke test runs after Alembic migrations and uses real JWT middleware,
PostgreSQL-backed sessions, and persisted-state assertions. It intentionally
creates two stores and checks that a supervisor from store A cannot read or
mutate store B inventory or warehouse placements.
"""
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token


def _bearer(user_id: int, role: str) -> dict[str, str]:
    token, _ = create_access_token(user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    suffix = uuid4().hex[:12]
    db = SessionLocal()
    try:
        store_a = models.Store(code=f"PG-AUTH-A-{suffix}", name="PG auth store A")
        store_b = models.Store(code=f"PG-AUTH-B-{suffix}", name="PG auth store B")
        product = models.Product(sku=f"PG-AUTH-{suffix}", name="PG auth product")
        db.add_all([store_a, store_b, product])
        db.flush()

        supervisor = models.User(
            email=f"pg-supervisor-{suffix}@example.test",
            full_name="PostgreSQL authorization supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store_a.id,
            is_active=True,
        )
        admin = models.User(
            email=f"pg-admin-{suffix}@example.test",
            full_name="PostgreSQL authorization admin",
            password_hash="smoke-test-only",
            role="ADMIN",
            store_id=None,
            is_active=True,
        )
        foreign_location = models.WarehouseLocation(
            store_id=store_b.id,
            code=f"PG-BIN-{suffix}",
            aisle="B",
            rack="01",
            bin_code="01",
            distance_to_picking_m=12,
            max_volume_cm3=100000,
            max_weight_kg=100,
        )
        db.add_all([supervisor, admin, foreign_location])
        db.flush()

        # Seed a completed foreign task and its source stock snapshot for
        # real JWT-backed cross-store authorization checks.
        foreign_zone = models.Zone(store_id=store_b.id, name="PG foreign task zone")
        db.add(foreign_zone)
        db.flush()
        foreign_shelf = models.Shelf(
            zone_id=foreign_zone.id,
            code=f"PG-TASK-SHELF-{suffix}",
        )
        db.add(foreign_shelf)
        db.flush()
        db.add(models.ShelfProduct(
            shelf_id=foreign_shelf.id,
            product_id=product.id,
            target_quantity=8,
            min_display_quantity=1,
        ))
        completed_at = models.utc_now()
        foreign_task = models.ReplenishmentTask(
            store_id=store_b.id,
            shelf_id=foreign_shelf.id,
            product_id=product.id,
            priority="NORMAL",
            status="COMPLETED",
            requested_quantity=2,
            actual_quantity=2,
            completed_at=completed_at,
        )
        db.add(foreign_task)
        db.add(models.InventorySnapshot(
            store_id=store_b.id,
            product_id=product.id,
            on_hand_quantity=10,
            reserved_quantity=0,
            source="WMS",
            external_reference=f"PG-AUTH-TASK-STOCK-{suffix}",
            captured_at=completed_at - timedelta(minutes=1),
        ))
        db.commit()
        store_a_id = store_a.id
        store_b_id = store_b.id
        product_id = product.id
        supervisor_id = supervisor.id
        admin_id = admin.id
        foreign_location_id = foreign_location.id
        foreign_shelf_id = foreign_shelf.id
        foreign_task_id = foreign_task.id
    finally:
        db.close()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(
        update={"app_env": "production"}
    )
    supervisor_headers = _bearer(supervisor_id, "SUPERVISOR")
    admin_headers = _bearer(admin_id, "ADMIN")

    try:
        with TestClient(app) as client:
            requests = {
                "inventory snapshot list": client.get(
                    "/api/v1/inventory/snapshots",
                    params={"store_id": store_b_id},
                    headers=supervisor_headers,
                ),
                "latest inventory snapshot": client.get(
                    "/api/v1/inventory/latest",
                    params={"store_id": store_b_id, "product_id": product_id},
                    headers=supervisor_headers,
                ),
                "inventory snapshot creation": client.post(
                    "/api/v1/inventory/snapshots",
                    json={
                        "store_id": store_b_id,
                        "product_id": product_id,
                        "on_hand_quantity": 24,
                        "reserved_quantity": 2,
                        "source": "MANUAL",
                        "external_reference": f"PG-AUTH-SNAPSHOT-{suffix}",
                    },
                    headers=supervisor_headers,
                ),
                "inventory freshness policy list": client.get(
                    "/api/v1/inventory/freshness-policies",
                    params={"store_id": store_b_id},
                    headers=supervisor_headers,
                ),
                "inventory freshness policy upsert": client.post(
                    "/api/v1/inventory/freshness-policies",
                    json={
                        "store_id": store_b_id,
                        "source": "MANUAL",
                        "max_age_minutes": 60,
                    },
                    headers=supervisor_headers,
                ),
                "warehouse placement creation": client.post(
                    "/api/v1/warehouse/placements",
                    json={
                        "location_id": foreign_location_id,
                        "product_id": product_id,
                        "quantity": 5,
                    },
                    headers=supervisor_headers,
                ),
                "warehouse slotting recommendations": client.get(
                    "/api/v1/warehouse/slotting-recommendations",
                    params={"store_id": store_b_id, "source": "POS"},
                    headers=supervisor_headers,
                ),
                "foreign task list": client.get(
                    "/api/v1/tasks",
                    params={"store_id": store_b_id},
                    headers=supervisor_headers,
                ),
                "foreign task lifecycle update": client.patch(
                    f"/api/v1/tasks/{foreign_task_id}/status",
                    json={"status": "CANCELLED", "exception_reason": "Cross-store authorization test"},
                    headers=supervisor_headers,
                ),
                "foreign task audit events": client.get(
                    f"/api/v1/tasks/{foreign_task_id}/events",
                    headers=supervisor_headers,
                ),
                "foreign task inventory reconciliation": client.post(
                    f"/api/v1/tasks/{foreign_task_id}/reconcile-inventory",
                    json={"reason": "Cross-store authorization test"},
                    headers=supervisor_headers,
                ),
                "task creation with foreign shelf": client.post(
                    "/api/v1/tasks",
                    json={
                        "store_id": store_a_id,
                        "shelf_id": foreign_shelf_id,
                        "product_id": product_id,
                        "requested_quantity": 1,
                    },
                    headers=supervisor_headers,
                ),
            }

            for resource, response in requests.items():
                expected_status = 404 if resource == "task creation with foreign shelf" else 403
                assert response.status_code == expected_status, (
                    f"SUPERVISOR must not access foreign {resource}; "
                    f"expected HTTP {expected_status}, received {response.status_code}: {response.text}"
                )
            assert requests["foreign task list"].json() == [], requests["foreign task list"].json()

            # Verify that denied writes left no rows in PostgreSQL.
            snapshots = client.get(
                "/api/v1/inventory/snapshots",
                params={"store_id": store_b_id},
                headers=admin_headers,
            )
            assert snapshots.status_code == 200, snapshots.text
            assert not any(
                item["external_reference"] == f"PG-AUTH-SNAPSHOT-{suffix}"
                for item in snapshots.json()
            ), snapshots.json()

            policies = client.get(
                "/api/v1/inventory/freshness-policies",
                params={"store_id": store_b_id},
                headers=admin_headers,
            )
            assert policies.status_code == 200, policies.text
            assert not any(
                item["source"] == "MANUAL" for item in policies.json()
            ), policies.json()

            db = SessionLocal()
            try:
                placement_count = (
                    db.query(models.WarehouseProductPlacement)
                    .filter(
                        models.WarehouseProductPlacement.location_id
                        == foreign_location_id,
                        models.WarehouseProductPlacement.product_id == product_id,
                    )
                    .count()
                )
                assert placement_count == 0, placement_count
            finally:
                db.close()

            # Denied task writes must leave the foreign task and stock unchanged.
            db = SessionLocal()
            try:
                persisted_task = db.get(models.ReplenishmentTask, foreign_task_id)
                assert persisted_task is not None
                assert persisted_task.status == "COMPLETED"
                assert (
                    db.query(models.InventoryMovement)
                    .filter(models.InventoryMovement.task_id == foreign_task_id)
                    .count()
                    == 0
                )
                assert (
                    db.query(models.ReplenishmentTaskEvent)
                    .filter(models.ReplenishmentTaskEvent.task_id == foreign_task_id)
                    .count()
                    == 0
                )
                assert (
                    db.query(models.ReplenishmentTask)
                    .filter(
                        models.ReplenishmentTask.store_id == store_a_id,
                        models.ReplenishmentTask.shelf_id == foreign_shelf_id,
                    )
                    .count()
                    == 0
                )
            finally:
                db.close()

            # The supervisor can still read and write its own store.
            own_snapshot = client.post(
                "/api/v1/inventory/snapshots",
                json={
                    "store_id": store_a_id,
                    "product_id": product_id,
                    "on_hand_quantity": 10,
                    "reserved_quantity": 1,
                    "source": "MANUAL",
                    "external_reference": f"PG-AUTH-OWN-{suffix}",
                },
                headers=supervisor_headers,
            )
            assert own_snapshot.status_code == 201, own_snapshot.text

            own_policy = client.post(
                "/api/v1/inventory/freshness-policies",
                json={
                    "store_id": store_a_id,
                    "source": "MANUAL",
                    "max_age_minutes": 90,
                },
                headers=supervisor_headers,
            )
            assert own_policy.status_code == 200, own_policy.text

    finally:
        main_module.settings = original_settings

    print(
        "PostgreSQL inventory authorization smoke passed: "
        "task list, lifecycle, audit and reconciliation denied across stores; foreign-shelf task creation rejected; inventory controls remain enforced, "
        "and same-store supervisor operations succeeded."
    )


if __name__ == "__main__":
    main()
