"""Verify capture-session tenant isolation against PostgreSQL with real JWTs.

Creates two stores and capture sessions, then checks supervisor scoping,
shelf filters, administrator visibility, and employee denial through HTTP.
"""
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token


def _bearer(user_id: int) -> dict[str, str]:
    token, _ = create_access_token(user_id=user_id)
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    suffix = uuid4().hex[:12]
    db = SessionLocal()
    try:
        store_a = models.Store(code=f"PG-CAPTURE-A-{suffix}", name="Capture store A")
        store_b = models.Store(code=f"PG-CAPTURE-B-{suffix}", name="Capture store B")
        db.add_all([store_a, store_b])
        db.flush()

        zone_a = models.Zone(store_id=store_a.id, name="Capture zone A")
        zone_b = models.Zone(store_id=store_b.id, name="Capture zone B")
        db.add_all([zone_a, zone_b])
        db.flush()

        shelf_a = models.Shelf(zone_id=zone_a.id, code=f"CAP-A-{suffix}")
        shelf_b = models.Shelf(zone_id=zone_b.id, code=f"CAP-B-{suffix}")
        db.add_all([shelf_a, shelf_b])
        db.flush()

        supervisor = models.User(
            email=f"pg-capture-supervisor-{suffix}@example.test",
            full_name="Capture supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store_a.id,
            is_active=True,
        )
        admin = models.User(
            email=f"pg-capture-admin-{suffix}@example.test",
            full_name="Capture administrator",
            password_hash="smoke-test-only",
            role="ADMIN",
            store_id=None,
            is_active=True,
        )
        employee = models.User(
            email=f"pg-capture-employee-{suffix}@example.test",
            full_name="Capture employee",
            password_hash="smoke-test-only",
            role="EMPLOYEE",
            store_id=store_a.id,
            is_active=True,
        )
        db.add_all([supervisor, admin, employee])
        db.flush()

        session_a = models.CaptureSession(
            store_id=store_a.id,
            shelf_id=shelf_a.id,
            source_type="mobile",
            capture_mode="single",
            created_by_user_id=supervisor.id,
        )
        session_b = models.CaptureSession(
            store_id=store_b.id,
            shelf_id=shelf_b.id,
            source_type="mobile",
            capture_mode="single",
            created_by_user_id=admin.id,
        )
        db.add_all([session_a, session_b])
        db.commit()

        store_a_id = store_a.id
        store_b_id = store_b.id
        shelf_a_id = shelf_a.id
        shelf_b_id = shelf_b.id
        supervisor_id = supervisor.id
        admin_id = admin.id
        employee_id = employee.id
    finally:
        db.close()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(update={"app_env": "production"})
    try:
        with TestClient(app) as client:
            supervisor_headers = _bearer(supervisor_id)
            own = client.get("/api/v1/capture-sessions", headers=supervisor_headers)
            assert own.status_code == 200, own.text
            own_rows = own.json()
            assert len(own_rows) == 1, own_rows
            assert own_rows[0]["store_id"] == store_a_id, own_rows

            own_shelf = client.get(
                "/api/v1/capture-sessions",
                params={"shelf_id": shelf_a_id},
                headers=supervisor_headers,
            )
            assert own_shelf.status_code == 200, own_shelf.text
            assert len(own_shelf.json()) == 1, own_shelf.json()
            assert own_shelf.json()[0]["shelf_id"] == shelf_a_id

            foreign_shelf = client.get(
                "/api/v1/capture-sessions",
                params={"shelf_id": shelf_b_id},
                headers=supervisor_headers,
            )
            assert foreign_shelf.status_code == 200, foreign_shelf.text
            assert foreign_shelf.json() == [], foreign_shelf.json()

            admin_response = client.get(
                "/api/v1/capture-sessions",
                headers=_bearer(admin_id),
            )
            assert admin_response.status_code == 200, admin_response.text
            admin_rows = admin_response.json()
            visible_stores = {row["store_id"] for row in admin_rows}
            assert {store_a_id, store_b_id}.issubset(visible_stores), admin_rows

            employee_response = client.get(
                "/api/v1/capture-sessions",
                headers=_bearer(employee_id),
            )
            assert employee_response.status_code == 403, employee_response.text
    finally:
        main_module.settings = original_settings

    print(
        "PostgreSQL capture-session authorization smoke passed: "
        "SUPERVISOR is store-scoped, foreign shelf filter is empty, "
        "ADMIN sees both stores, and EMPLOYEE is denied."
    )


if __name__ == "__main__":
    main()
