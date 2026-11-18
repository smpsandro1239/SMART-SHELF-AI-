"""Verify the store employee directory authorization against PostgreSQL.

Creates two stores with active and inactive employees, then exercises the
real HTTP endpoint with signed JWTs for SUPERVISOR, ADMIN and EMPLOYEE.
"""
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
        store_a = models.Store(code=f"PG-EMPLOYEE-A-{suffix}", name="Employee store A")
        store_b = models.Store(code=f"PG-EMPLOYEE-B-{suffix}", name="Employee store B")
        db.add_all([store_a, store_b])
        db.flush()

        supervisor = models.User(
            email=f"pg-employee-supervisor-{suffix}@example.test",
            full_name="Directory supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store_a.id,
            is_active=True,
        )
        admin = models.User(
            email=f"pg-employee-admin-{suffix}@example.test",
            full_name="Directory administrator",
            password_hash="smoke-test-only",
            role="ADMIN",
            store_id=None,
            is_active=True,
        )
        inactive_supervisor = models.User(
            email=f"pg-employee-inactive-supervisor-{suffix}@example.test",
            full_name="Inactive directory supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store_a.id,
            is_active=False,
        )
        employee_a = models.User(
            email=f"pg-employee-a-{suffix}@example.test",
            full_name="Active employee A",
            password_hash="smoke-test-only",
            role="EMPLOYEE",
            store_id=store_a.id,
            is_active=True,
        )
        employee_b = models.User(
            email=f"pg-employee-b-{suffix}@example.test",
            full_name="Active employee B",
            password_hash="smoke-test-only",
            role="EMPLOYEE",
            store_id=store_b.id,
            is_active=True,
        )
        inactive_employee_a = models.User(
            email=f"pg-employee-inactive-{suffix}@example.test",
            full_name="Inactive employee A",
            password_hash="smoke-test-only",
            role="EMPLOYEE",
            store_id=store_a.id,
            is_active=False,
        )
        db.add_all([
            supervisor, admin, inactive_supervisor,
            employee_a, employee_b, inactive_employee_a,
        ])
        db.commit()

        store_a_id = store_a.id
        store_b_id = store_b.id
        supervisor_id = supervisor.id
        admin_id = admin.id
        inactive_supervisor_id = inactive_supervisor.id
        employee_a_id = employee_a.id
        employee_b_id = employee_b.id
    finally:
        db.close()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(update={"app_env": "production"})
    try:
        with TestClient(app) as client:
            missing_token = client.get("/api/v1/store-employees")
            assert missing_token.status_code == 401, missing_token.text

            invalid_token = client.get(
                "/api/v1/store-employees",
                headers={"Authorization": "Bearer invalid.jwt.token"},
            )
            assert invalid_token.status_code == 401, invalid_token.text

            inactive_account = client.get(
                "/api/v1/store-employees",
                headers=_bearer(inactive_supervisor_id, "SUPERVISOR"),
            )
            assert inactive_account.status_code == 401, inactive_account.text

            supervisor_headers = _bearer(supervisor_id, "SUPERVISOR")
            own_response = client.get("/api/v1/store-employees", headers=supervisor_headers)
            assert own_response.status_code == 200, own_response.text
            own_rows = own_response.json()
            assert {row["id"] for row in own_rows} == {employee_a_id}, own_rows
            assert all(row["store_id"] == store_a_id for row in own_rows), own_rows
            assert all(row["is_active"] for row in own_rows), own_rows

            foreign_response = client.get(
                "/api/v1/store-employees",
                params={"store_id": store_b_id},
                headers=supervisor_headers,
            )
            assert foreign_response.status_code == 403, foreign_response.text

            admin_headers = _bearer(admin_id, "ADMIN")
            admin_response = client.get(
                "/api/v1/store-employees",
                params={"store_id": store_b_id},
                headers=admin_headers,
            )
            assert admin_response.status_code == 200, admin_response.text
            assert {row["id"] for row in admin_response.json()} == {employee_b_id}

            admin_global_response = client.get(
                "/api/v1/store-employees",
                headers=admin_headers,
            )
            assert admin_global_response.status_code == 200, admin_global_response.text
            assert {row["id"] for row in admin_global_response.json()} == {
                employee_a_id, employee_b_id
            }, admin_global_response.json()

            employee_response = client.get(
                "/api/v1/store-employees",
                headers=_bearer(employee_a_id, "EMPLOYEE"),
            )
            assert employee_response.status_code == 403, employee_response.text
    finally:
        main_module.settings = original_settings

    print(
        "PostgreSQL store employee authorization smoke passed: "
        "missing/invalid/inactive identities are rejected, SUPERVISOR sees "
        "active employees in their store only, ADMIN sees active employees "
        "globally or by store, and EMPLOYEE is denied."
    )


if __name__ == "__main__":
    main()
