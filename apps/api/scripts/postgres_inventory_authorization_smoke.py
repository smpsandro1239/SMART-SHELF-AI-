"""Verify cross-store authorization for inventory, warehouse and operations APIs.

This PostgreSQL 16 smoke uses real JWT middleware, database-backed sessions and
persisted-state assertions. It checks cross-store writes and a broad matrix of
store_id-scoped sales, forecasting, replenishment and warehouse reads.
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

        # Seed valid same-store and foreign-store resources so the positive
        # controls exercise real nested identifiers rather than 404 fallbacks.
        packaging = models.ProductPackagingLevel(
            product_id=product.id,
            code="CASE",
            name="Case of 12",
            package_type="CASE",
            base_units_per_package=12,
            is_ordering_unit=True,
            is_replenishment_unit=True,
        )
        db.add(packaging)
        db.flush()
        own_pallet = models.StorePallet(
            store_id=store_a.id,
            product_id=product.id,
            packaging_level_id=packaging.id,
            pallet_code=f"PG-PALLET-A-{suffix}",
            base_quantity=12,
            status="ON_DISPLAY",
            location_type="SALES_FLOOR",
        )
        foreign_pallet = models.StorePallet(
            store_id=store_b.id,
            product_id=product.id,
            packaging_level_id=packaging.id,
            pallet_code=f"PG-PALLET-B-{suffix}",
            base_quantity=12,
            status="READY",
            location_type="WAREHOUSE",
        )
        db.add_all([own_pallet, foreign_pallet])
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
        own_location = models.WarehouseLocation(
            store_id=store_a.id,
            code=f"PG-BIN-A-{suffix}",
            aisle="A",
            rack="01",
            bin_code="01",
            distance_to_picking_m=8,
            max_volume_cm3=100000,
            max_weight_kg=100,
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
        db.add_all([supervisor, admin, own_location, foreign_location])
        db.flush()

        # Seed a completed foreign task and its source stock snapshot for
        # real JWT-backed cross-store authorization checks.
        own_zone = models.Zone(store_id=store_a.id, name="PG own task zone")
        foreign_zone = models.Zone(store_id=store_b.id, name="PG foreign task zone")
        db.add_all([own_zone, foreign_zone])
        db.flush()
        own_shelf = models.Shelf(zone_id=own_zone.id, code=f"PG-OWN-SHELF-{suffix}")
        foreign_shelf = models.Shelf(
            zone_id=foreign_zone.id,
            code=f"PG-TASK-SHELF-{suffix}",
        )
        db.add_all([own_shelf, foreign_shelf])
        db.flush()
        db.add_all([
            models.ShelfProduct(
                shelf_id=own_shelf.id,
                product_id=product.id,
                target_quantity=8,
                min_display_quantity=1,
            ),
            models.ShelfProduct(
                shelf_id=foreign_shelf.id,
                product_id=product.id,
                target_quantity=8,
                min_display_quantity=1,
            ),
        ])
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
        own_location_id = own_location.id
        foreign_location_id = foreign_location.id
        own_shelf_id = own_shelf.id
        foreign_shelf_id = foreign_shelf.id
        own_pallet_id = own_pallet.id
        foreign_pallet_id = foreign_pallet.id
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

            # Exercise read-only store_id query parameters across forecasting,
            # sales, replenishment and warehouse APIs. The scope guard must
            # reject the foreign tenant before reading any of its data.
            foreign_store_reads = [
                ("daily sales history", "/api/v1/sales/daily", {
                    "store_id": store_b_id, "product_id": product_id, "source": "POS",
                }),
                ("hourly sales history", "/api/v1/sales/hourly", {
                    "store_id": store_b_id,
                }),
                ("hourly traffic history", "/api/v1/sales/traffic/hourly", {
                    "store_id": store_b_id,
                }),
                ("pallet hourly profile", "/api/v1/warehouse/pallet-rotation/hourly-profile", {
                    "store_id": store_b_id, "product_id": product_id,
                }),
                ("traffic peaks", "/api/v1/forecasting/traffic-peaks", {
                    "store_id": store_b_id,
                }),
                ("hourly demand forecast", "/api/v1/forecasting/hourly-demand", {
                    "store_id": store_b_id, "product_id": product_id,
                }),
                ("weekday hourly profile", "/api/v1/warehouse/pallet-rotation/weekday-hourly-profile", {
                    "store_id": store_b_id, "product_id": product_id,
                }),
                ("pallet rotation window", "/api/v1/warehouse/pallet-rotation/window-plan", {
                    "store_id": store_b_id, "product_id": product_id,
                    "pallet_id": foreign_pallet_id, "current_hour": 12, "residual_base_units": 5,
                }),
                ("history-based pallet portfolio", "/api/v1/warehouse/pallet-rotation/portfolio-from-history", {
                    "store_id": store_b_id, "current_hour": 12,
                }),
                ("pallet portfolio", "/api/v1/warehouse/pallet-rotation/portfolio", {
                    "store_id": store_b_id, "traffic_level": "LOW",
                    "forecast_consumption_until_low_traffic": 5,
                }),
                ("replenishment unit calculation", "/api/v1/warehouse/replenishment-units", {
                    "store_id": store_b_id, "product_id": product_id,
                    "required_base_units": 5, "packaging_code": "CASE",
                }),
                ("physical warehouse slotting", "/api/v1/warehouse/physical-slotting", {
                    "store_id": store_b_id, "product_id": product_id, "required_quantity": 5,
                }),
                ("daily demand forecast", "/api/v1/forecasting/demand", {
                    "store_id": store_b_id, "product_id": product_id,
                    "source": "POS", "lead_time_days": 2,
                }),
                ("stockout risk", "/api/v1/forecasting/stockout-risk", {
                    "store_id": store_b_id, "product_id": product_id,
                    "source": "POS", "lead_time_days": 2,
                }),
                ("store stockout risk portfolio", "/api/v1/forecasting/stockout-risk/portfolio", {
                    "store_id": store_b_id, "source": "POS", "lead_time_days": 2,
                }),
                ("replenishment recommendations", "/api/v1/replenishment/recommendations", {
                    "store_id": store_b_id,
                }),
                ("replenishment plan", "/api/v1/replenishment/plan", {
                    "store_id": store_b_id,
                }),
                ("replenishment workload", "/api/v1/replenishment/workload", {
                    "store_id": store_b_id,
                }),
                ("operational decisions", "/api/v1/operational-decisions", {
                    "store_id": store_b_id,
                }),
                ("warehouse locations", "/api/v1/warehouse/locations", {
                    "store_id": store_b_id,
                }),
                ("store pallets", "/api/v1/warehouse/pallets", {
                    "store_id": store_b_id,
                }),
                ("pallet rotation policies", "/api/v1/warehouse/pallet-rotation/policies", {
                    "store_id": store_b_id,
                }),
                ("pallet lifecycle events", f"/api/v1/warehouse/pallets/{foreign_pallet_id}/events", {
                    "store_id": store_b_id,
                }),
            ]
            for resource, path, params in foreign_store_reads:
                requests[f"foreign {resource}"] = client.get(
                    path, params=params, headers=supervisor_headers,
                )

            # Positive control: the same supervisor must be able to execute
            # every store-scoped read inside its own tenant. Real packaging
            # and pallet rows are seeded above so nested identifiers exercise
            # successful same-store paths rather than missing-row fallbacks.
            same_store_read_count = 0
            for resource, path, params in foreign_store_reads:
                own_params = dict(params)
                own_params["store_id"] = store_a_id
                if resource == "pallet rotation window":
                    own_params["pallet_id"] = own_pallet_id
                    own_params["residual_base_units"] = 12
                if resource == "pallet lifecycle events":
                    path = f"/api/v1/warehouse/pallets/{own_pallet_id}/events"
                response = client.get(
                    path, params=own_params, headers=supervisor_headers,
                )
                assert response.status_code == 200, (
                    f"SUPERVISOR must be able to read own-store {resource}; "
                    f"expected HTTP 200, received {response.status_code}: {response.text}"
                )
                same_store_read_count += 1
            assert same_store_read_count == len(foreign_store_reads)

            # Nested-ID BOLA controls: the caller is authorized for store A
            # and supplies store A as the scope, but references real resources
            # owned by store B. These must not be accepted merely because the
            # top-level store_id is valid for the caller.
            foreign_pallet_window = client.get(
                "/api/v1/warehouse/pallet-rotation/window-plan",
                params={
                    "store_id": store_a_id,
                    "product_id": product_id,
                    "pallet_id": foreign_pallet_id,
                    "current_hour": 12,
                    "residual_base_units": 12,
                },
                headers=supervisor_headers,
            )
            assert foreign_pallet_window.status_code == 404, (
                "SUPERVISOR must not resolve a foreign pallet through an own-store "
                f"rotation request; received {foreign_pallet_window.status_code}: "
                f"{foreign_pallet_window.text}"
            )

            foreign_pallet_events = client.get(
                f"/api/v1/warehouse/pallets/{foreign_pallet_id}/events",
                params={"store_id": store_a_id},
                headers=supervisor_headers,
            )
            assert foreign_pallet_events.status_code == 404, (
                "SUPERVISOR must not resolve foreign pallet lifecycle events "
                f"through an own-store request; received {foreign_pallet_events.status_code}: "
                f"{foreign_pallet_events.text}"
            )

            for resource, response in requests.items():
                expected_status = (
                    404 if resource == "task creation with foreign shelf"
                    else 403
                )
                assert response.status_code == expected_status, (
                    f"SUPERVISOR must not access foreign {resource}; "
                    f"expected HTTP {expected_status}, received {response.status_code}: {response.text}"
                )

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

            # Positive controls for nested resource IDs: a valid location and
            # shelf belonging to the caller's own store must remain usable.
            own_placement = client.post(
                "/api/v1/warehouse/placements",
                json={
                    "location_id": own_location_id,
                    "product_id": product_id,
                    "quantity": 5,
                },
                headers=supervisor_headers,
            )
            assert own_placement.status_code == 201, own_placement.text

            own_task = client.post(
                "/api/v1/tasks",
                json={
                    "store_id": store_a_id,
                    "shelf_id": own_shelf_id,
                    "product_id": product_id,
                    "requested_quantity": 1,
                },
                headers=supervisor_headers,
            )
            assert own_task.status_code == 201, own_task.text

    finally:
        main_module.settings = original_settings

    print(
        "PostgreSQL inventory/operations authorization smoke passed: cross-store "
        "inventory, task and warehouse writes were denied without persistence; "
        "store-scoped sales, forecast, replenishment and warehouse reads were "
        "denied; same-store supervisor operations succeeded."
    )


if __name__ == "__main__":
    main()
