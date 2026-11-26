"""Verify cross-store authorization for inventory, warehouse and operations APIs.

This PostgreSQL 16 smoke uses real JWT middleware, database-backed sessions and
persisted-state assertions. It checks cross-store writes and a broad matrix of
store_id-scoped sales, forecasting, replenishment and warehouse reads.
"""
from datetime import date, timedelta
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
        own_rotation_policy = models.PalletRotationPolicy(
            store_id=store_a.id,
            product_id=product.id,
            threshold_ratio=0.5,
            is_enabled=True,
        )
        foreign_rotation_policy = models.PalletRotationPolicy(
            store_id=store_b.id,
            product_id=product.id,
            threshold_ratio=0.5,
            is_enabled=True,
        )
        db.add_all([own_rotation_policy, foreign_rotation_policy])
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
        employee = models.User(
            email=f"pg-employee-{suffix}@example.test",
            full_name="PostgreSQL authorization employee",
            password_hash="smoke-test-only",
            role="EMPLOYEE",
            store_id=store_a.id,
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
        db.add_all([supervisor, admin, employee, own_location, foreign_location])
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
        # Materialise SKU-to-shelf links before inserting alerts. PostgreSQL
        # migration 0099 enforces this lineage in a BEFORE INSERT trigger; the
        # ORM unit-of-work does not infer an ordering dependency between these
        # independent model instances merely because they share FK values.
        db.flush()
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
        foreign_observation = models.Observation(
            shelf_id=foreign_shelf.id,
            product_id=product.id,
            source="fixed_camera",
            status="LOW_STOCK",
            confidence=0.9,
            observed_quantity=1,
            observed_at=completed_at,
            model_version="authorization-smoke",
        )
        foreign_capture_session = models.CaptureSession(
            store_id=store_b.id,
            shelf_id=foreign_shelf.id,
            source_type="fixed_camera",
            capture_mode="single",
            started_at=completed_at,
        )
        foreign_alert = models.ObservationAlert(
            store_id=store_b.id,
            shelf_id=foreign_shelf.id,
            product_id=product.id,
            condition="LOW_STOCK",
            status="OPEN",
            first_seen_at=completed_at,
            last_seen_at=completed_at,
            confirmation_count=2,
            average_confidence=0.9,
            sources=["fixed_camera"],
        )
        db.add_all([foreign_observation, foreign_capture_session, foreign_alert])
        db.flush()
        foreign_observation_id = foreign_observation.id
        foreign_capture_session_id = foreign_capture_session.id
        foreign_alert_id = foreign_alert.id
        db.add(models.ObservationAlertEvent(
            alert_id=foreign_alert.id,
            event_type="CREATED",
            to_status="OPEN",
            reason="PostgreSQL authorization smoke fixture",
            created_at=completed_at,
        ))
        db.add(models.InventorySnapshot(
            store_id=store_b.id,
            product_id=product.id,
            on_hand_quantity=10,
            reserved_quantity=0,
            source="WMS",
            external_reference=f"PG-AUTH-TASK-STOCK-{suffix}",
            location_code="BACKROOM-A",
            availability_status="AVAILABLE",
            captured_at=completed_at - timedelta(minutes=1),
        ))
        # Forecast positive controls require an explicit record for every
        # calendar day in the default 28-day window. Zero is a confirmed
        # zero-sales day, not a missing observation.
        today = date.today()
        db.add_all([
            models.DailySalesRecord(
                store_id=store_a.id,
                product_id=product.id,
                sales_date=today - timedelta(days=offset),
                quantity=0,
                source="POS",
                external_reference=f"PG-AUTH-DAILY-{suffix}-{offset}",
            )
            for offset in range(28)
        ])
        db.add(models.InventorySnapshot(
            store_id=store_a.id,
            product_id=product.id,
            on_hand_quantity=10,
            reserved_quantity=0,
            source="WMS",
            external_reference=f"PG-AUTH-OWN-STOCK-{suffix}",
            location_code="BACKROOM-A",
            availability_status="AVAILABLE",
            captured_at=completed_at,
        ))
        db.commit()
        store_a_id = store_a.id
        store_b_id = store_b.id
        product_id = product.id
        supervisor_id = supervisor.id
        admin_id = admin.id
        employee_id = employee.id
        own_location_id = own_location.id
        foreign_location_id = foreign_location.id
        own_shelf_id = own_shelf.id
        foreign_shelf_id = foreign_shelf.id
        own_pallet_id = own_pallet.id
        foreign_pallet_id = foreign_pallet.id
        foreign_rotation_policy_id = foreign_rotation_policy.id
        foreign_task_id = foreign_task.id
    finally:
        db.close()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(
        update={"app_env": "production"}
    )
    supervisor_headers = _bearer(supervisor_id, "SUPERVISOR")
    admin_headers = _bearer(admin_id, "ADMIN")
    employee_headers = _bearer(employee_id, "EMPLOYEE")

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
                        "reason": "Cross-store authorization regression",
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
                "observation creation with foreign shelf": client.post(
                    "/api/v1/observations",
                    json={
                        "shelf_id": foreign_shelf_id,
                        "product_id": product_id,
                        "source": "mobile",
                        "status": "UNKNOWN",
                    },
                    headers=supervisor_headers,
                ),
                "capture session creation with foreign shelf": client.post(
                    "/api/v1/capture-sessions",
                    json={
                        "shelf_id": foreign_shelf_id,
                        "source_type": "mobile",
                        "capture_mode": "single",
                    },
                    headers=supervisor_headers,
                ),
                "planogram creation with foreign shelf": client.post(
                    f"/api/v1/shelves/{foreign_shelf_id}/planograms",
                    json={
                        "calibration_source": "MANUAL",
                        "cells": [{
                            "cell_code": "FOREIGN-CELL",
                            "row_index": 0,
                            "column_index": 0,
                            "x_min": 0.0,
                            "y_min": 0.0,
                            "x_max": 1.0,
                            "y_max": 1.0,
                            "expected_product_id": product_id,
                            "expected_facings": 1,
                        }],
                    },
                    headers=supervisor_headers,
                ),
                "foreign observation alert events": client.get(
                    f"/api/v1/observation-alerts/{foreign_alert_id}/events",
                    headers=supervisor_headers,
                ),
            }

            # Nested shelf filters must not disclose rows belonging to another
            # tenant, even when the caller supplies a real foreign shelf ID.
            nested_filtered_reads = {
                "foreign shelf observations": client.get(
                    "/api/v1/observations",
                    params={"shelf_id": foreign_shelf_id},
                    headers=supervisor_headers,
                ),
                "foreign shelf capture sessions": client.get(
                    "/api/v1/capture-sessions",
                    params={"shelf_id": foreign_shelf_id},
                    headers=supervisor_headers,
                ),
                "foreign shelf alerts": client.get(
                    "/api/v1/observation-alerts",
                    params={"shelf_id": foreign_shelf_id},
                    headers=supervisor_headers,
                ),
            }
            for resource, response in nested_filtered_reads.items():
                assert response.status_code == 200, (
                    f"SUPERVISOR nested {resource} query should be safely scoped; "
                    f"received {response.status_code}: {response.text}"
                )
                assert response.json() == [], (
                    f"SUPERVISOR must not receive foreign rows from {resource}: "
                    f"{response.json()}"
                )

            # ADMIN is the cross-store control: prove the foreign fixtures are
            # real and visible to the privileged actor, not merely absent data.
            admin_foreign_observations = client.get(
                "/api/v1/observations",
                params={"shelf_id": foreign_shelf_id},
                headers=admin_headers,
            )
            admin_foreign_sessions = client.get(
                "/api/v1/capture-sessions",
                params={"shelf_id": foreign_shelf_id},
                headers=admin_headers,
            )
            admin_foreign_alerts = client.get(
                "/api/v1/observation-alerts",
                params={"shelf_id": foreign_shelf_id},
                headers=admin_headers,
            )
            assert admin_foreign_observations.status_code == 200
            assert foreign_observation_id in {
                item["id"] for item in admin_foreign_observations.json()
            }
            assert admin_foreign_sessions.status_code == 200
            assert foreign_capture_session_id in {
                item["id"] for item in admin_foreign_sessions.json()
            }
            assert admin_foreign_alerts.status_code == 200
            assert foreign_alert_id in {
                item["id"] for item in admin_foreign_alerts.json()
            }

            # EMPLOYEE is denied by the explicit RBAC policy even for resources
            # belonging to the employee's own store.
            employee_denied_reads = {
                "observations": client.get(
                    "/api/v1/observations",
                    params={"shelf_id": own_shelf_id},
                    headers=employee_headers,
                ),
                "capture sessions": client.get(
                    "/api/v1/capture-sessions",
                    params={"shelf_id": own_shelf_id},
                    headers=employee_headers,
                ),
                "observation alerts": client.get(
                    "/api/v1/observation-alerts",
                    headers=employee_headers,
                ),
                "planograms": client.get(
                    f"/api/v1/shelves/{own_shelf_id}/planograms",
                    headers=employee_headers,
                ),
            }
            for resource, response in employee_denied_reads.items():
                assert response.status_code == 403, (
                    f"EMPLOYEE must not read {resource}; expected HTTP 403, "
                    f"received {response.status_code}: {response.text}"
                )

            nested_shelf_reads = {
                "foreign shelf observation consensus": client.get(
                    f"/api/v1/shelves/{foreign_shelf_id}/observation-consensus",
                    headers=supervisor_headers,
                ),
                "foreign shelf planograms": client.get(
                    f"/api/v1/shelves/{foreign_shelf_id}/planograms",
                    headers=supervisor_headers,
                ),
                "foreign active shelf planogram": client.get(
                    f"/api/v1/shelves/{foreign_shelf_id}/planograms/active",
                    headers=supervisor_headers,
                ),
            }
            for resource, response in nested_shelf_reads.items():
                expected_status = 404
                assert response.status_code == expected_status, (
                    f"SUPERVISOR must not resolve {resource}; expected HTTP {expected_status}, "
                    f"received {response.status_code}: {response.text}"
                )

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

            missing_pallet_events = client.get(
                "/api/v1/warehouse/pallets/-1/events",
                params={"store_id": store_a_id},
                headers=supervisor_headers,
            )
            assert missing_pallet_events.status_code == 404, (
                "A missing pallet lifecycle history must return HTTP 404; "
                f"received {missing_pallet_events.status_code}: {missing_pallet_events.text}"
            )
            assert foreign_pallet_events.text == missing_pallet_events.text, (
                "Foreign and missing pallet IDs must expose indistinguishable "
                f"lifecycle-history responses: foreign={foreign_pallet_events.text!r}, "
                f"missing={missing_pallet_events.text!r}"
            )

            lifecycle_update = {
                "expected_status": "READY",
                "expected_base_quantity": 12,
                "status": "ON_DISPLAY",
                "location_type": "SALES_FLOOR",
                "reason": "Cross-store authorization regression",
            }
            foreign_pallet_update = client.post(
                f"/api/v1/warehouse/pallets/{foreign_pallet_id}/events",
                json=lifecycle_update,
                headers=supervisor_headers,
            )
            missing_pallet_update = client.post(
                "/api/v1/warehouse/pallets/-1/events",
                json=lifecycle_update,
                headers=supervisor_headers,
            )
            assert foreign_pallet_update.status_code == 404, foreign_pallet_update.text
            assert missing_pallet_update.status_code == 404, missing_pallet_update.text
            assert foreign_pallet_update.text == missing_pallet_update.text, (
                "Foreign and missing pallet IDs must expose indistinguishable "
                f"lifecycle-write responses: foreign={foreign_pallet_update.text!r}, "
                f"missing={missing_pallet_update.text!r}"
            )

            foreign_policy_update = client.patch(
                f"/api/v1/warehouse/pallet-rotation/policies/{foreign_rotation_policy_id}",
                json={"is_enabled": False},
                headers=supervisor_headers,
            )
            missing_policy_update = client.patch(
                "/api/v1/warehouse/pallet-rotation/policies/-1",
                json={"is_enabled": False},
                headers=supervisor_headers,
            )
            assert foreign_policy_update.status_code == 404, foreign_policy_update.text
            assert missing_policy_update.status_code == 404, missing_policy_update.text
            assert foreign_policy_update.text == missing_policy_update.text, (
                "Foreign and missing policy IDs must expose indistinguishable "
                f"responses: foreign={foreign_policy_update.text!r}, "
                f"missing={missing_policy_update.text!r}"
            )

            own_pallet_update = client.post(
                f"/api/v1/warehouse/pallets/{own_pallet_id}/events",
                json={
                    "expected_status": "ON_DISPLAY",
                    "expected_base_quantity": 12,
                    "status": "PARTIAL",
                    "base_quantity": 10,
                    "reason": "Same-store lifecycle positive control",
                },
                headers=supervisor_headers,
            )
            assert own_pallet_update.status_code == 201, own_pallet_update.text
            assert own_pallet_update.json()["pallet_id"] == own_pallet_id

            for resource, response in requests.items():
                expected_status = (
                    404
                    if resource in {
                        "task creation with foreign shelf",
                        "warehouse placement creation",
                        "foreign task lifecycle update",
                        "foreign task audit events",
                        "foreign task inventory reconciliation",
                        "observation creation with foreign shelf",
                        "capture session creation with foreign shelf",
                        "foreign observation alert events",
                        "planogram creation with foreign shelf",
                    }
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

                foreign_pallet_state = db.get(models.StorePallet, foreign_pallet_id)
                assert foreign_pallet_state is not None
                assert foreign_pallet_state.status == "READY"
                assert float(foreign_pallet_state.base_quantity) == 12
                assert db.query(models.PalletRotationEvent).filter_by(
                    pallet_id=foreign_pallet_id
                ).count() == 0

                foreign_policy_state = db.get(
                    models.PalletRotationPolicy,
                    foreign_rotation_policy_id,
                )
                assert foreign_policy_state is not None
                assert foreign_policy_state.is_enabled is True
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
                persisted_observation = db.get(models.Observation, foreign_observation_id)
                assert persisted_observation is not None
                assert persisted_observation.shelf_id == foreign_shelf_id
                assert persisted_observation.model_version == "authorization-smoke"
                assert (
                    db.query(models.Observation)
                    .filter(
                        models.Observation.shelf_id == foreign_shelf_id,
                        models.Observation.source == "mobile",
                        models.Observation.status == "UNKNOWN",
                    )
                    .count()
                    == 0
                )
                persisted_capture_session = db.get(
                    models.CaptureSession, foreign_capture_session_id
                )
                assert persisted_capture_session is not None
                assert persisted_capture_session.store_id == store_b_id
                assert persisted_capture_session.shelf_id == foreign_shelf_id
                assert (
                    db.query(models.ObservationAlert)
                    .filter(
                        models.ObservationAlert.id == foreign_alert_id,
                        models.ObservationAlert.status == "OPEN",
                    )
                    .count()
                    == 1
                )
                assert (
                    db.query(models.ObservationAlertEvent)
                    .filter(models.ObservationAlertEvent.alert_id == foreign_alert_id)
                    .count()
                    == 1
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
                    "reason": "Same-store manual count authorization positive control",
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

            own_observation = client.post(
                "/api/v1/observations",
                json={
                    "shelf_id": own_shelf_id,
                    "product_id": product_id,
                    "source": "mobile",
                    "status": "UNKNOWN",
                },
                headers=supervisor_headers,
            )
            assert own_observation.status_code == 201, own_observation.text

            own_capture_session = client.post(
                "/api/v1/capture-sessions",
                json={
                    "shelf_id": own_shelf_id,
                    "source_type": "mobile",
                    "capture_mode": "single",
                },
                headers=supervisor_headers,
            )
            assert own_capture_session.status_code == 201, own_capture_session.text

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
