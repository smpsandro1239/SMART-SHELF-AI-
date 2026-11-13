import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app.database import Base, get_db
from app import models
from app.models import Store, User
from app.security import create_access_token, hash_password


@pytest.fixture
def auth_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    store_a = Store(code="AUTH-A", name="Auth Store A")
    store_b = Store(code="AUTH-B", name="Auth Store B")
    with session_factory() as db:
        db.add_all([store_a, store_b])
        db.flush()
        users = {
            "admin": User(
                email="admin@example.test", full_name="Admin",
                password_hash=hash_password("test-password"), role="ADMIN",
                store_id=None, is_active=True,
            ),
            "supervisor_a": User(
                email="supervisor-a@example.test", full_name="Supervisor A",
                password_hash=hash_password("test-password"), role="SUPERVISOR",
                store_id=store_a.id, is_active=True,
            ),
            "employee_a": User(
                email="employee-a@example.test", full_name="Employee A",
                password_hash=hash_password("test-password"), role="EMPLOYEE",
                store_id=store_a.id, is_active=True,
            ),
            "employee_a_peer": User(
                email="employee-a-peer@example.test", full_name="Employee A Peer",
                password_hash=hash_password("test-password"), role="EMPLOYEE",
                store_id=store_a.id, is_active=True,
            ),
            "employee_b": User(
                email="employee-b@example.test", full_name="Employee B",
                password_hash=hash_password("test-password"), role="EMPLOYEE",
                store_id=store_b.id, is_active=True,
            ),
            "inactive": User(
                email="inactive@example.test", full_name="Inactive",
                password_hash=hash_password("test-password"), role="ADMIN",
                store_id=None, is_active=False,
            ),
        }
        db.add_all(users.values())
        db.flush()

        product = models.Product(sku="AUTH-TASK-SKU", name="Produto de teste")
        zone_a = models.Zone(store_id=store_a.id, name="Zona A")
        zone_b = models.Zone(store_id=store_b.id, name="Zona B")
        db.add_all([product, zone_a, zone_b])
        db.flush()
        shelf_a_assigned = models.Shelf(zone_id=zone_a.id, code="A-ASSIGNED")
        shelf_a_unassigned = models.Shelf(zone_id=zone_a.id, code="A-UNASSIGNED")
        shelf_a_peer = models.Shelf(zone_id=zone_a.id, code="A-PEER")
        shelf_b = models.Shelf(zone_id=zone_b.id, code="B-ASSIGNED")
        db.add_all([shelf_a_assigned, shelf_a_unassigned, shelf_a_peer, shelf_b])
        db.flush()
        db.add_all([
            models.ShelfProduct(shelf_id=shelf_a_assigned.id, product_id=product.id, target_quantity=10, min_display_quantity=2),
            models.ShelfProduct(shelf_id=shelf_a_unassigned.id, product_id=product.id, target_quantity=10, min_display_quantity=2),
            models.ShelfProduct(shelf_id=shelf_a_peer.id, product_id=product.id, target_quantity=10, min_display_quantity=2),
            models.ShelfProduct(shelf_id=shelf_b.id, product_id=product.id, target_quantity=10, min_display_quantity=2),
        ])
        task_a_assigned = models.ReplenishmentTask(
            store_id=store_a.id, shelf_id=shelf_a_assigned.id, product_id=product.id,
            status="ASSIGNED", assigned_to=users["employee_a"].full_name,
            assigned_user_id=users["employee_a"].id, requested_quantity=5,
        )
        task_a_unassigned = models.ReplenishmentTask(
            store_id=store_a.id, shelf_id=shelf_a_unassigned.id, product_id=product.id,
            status="PENDING", requested_quantity=4,
        )
        task_a_peer = models.ReplenishmentTask(
            store_id=store_a.id, shelf_id=shelf_a_peer.id, product_id=product.id,
            status="ASSIGNED", assigned_to=users["employee_a_peer"].full_name,
            assigned_user_id=users["employee_a_peer"].id, requested_quantity=2,
        )
        task_b_assigned = models.ReplenishmentTask(
            store_id=store_b.id, shelf_id=shelf_b.id, product_id=product.id,
            status="ASSIGNED", assigned_to=users["employee_b"].full_name,
            assigned_user_id=users["employee_b"].id, requested_quantity=3,
        )
        db.add_all([task_a_assigned, task_a_unassigned, task_a_peer, task_b_assigned])
        db.flush()
        db.add_all([
            models.ReplenishmentTaskEvent(task_id=task.id, event_type="CREATED", to_status=task.status)
            for task in (task_a_assigned, task_a_unassigned, task_a_peer, task_b_assigned)
        ])
        db.commit()
        ids = {key: user.id for key, user in users.items()}
        ids["task_a_assigned"] = task_a_assigned.id
        ids["task_a_unassigned"] = task_a_unassigned.id
        ids["task_a_peer"] = task_a_peer.id
        ids["task_b_assigned"] = task_b_assigned.id
        store_ids = {"a": store_a.id, "b": store_b.id}

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    previous_override = main_module.app.dependency_overrides.get(get_db)
    original_settings = main_module.settings
    main_module.app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    # Keep production mode local to this module; do not mutate the shared Settings singleton.
    monkeypatch.setattr(
        main_module,
        "settings",
        original_settings.model_copy(update={"app_env": "production"}),
    )

    try:
        with TestClient(main_module.app) as client:
            yield client, ids, store_ids
    finally:
        # Restore immediately, before pytest runs any other module's API tests.
        main_module.settings = original_settings
        if previous_override is None:
            main_module.app.dependency_overrides.pop(get_db, None)
        else:
            main_module.app.dependency_overrides[get_db] = previous_override
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def bearer(user_id: int, role_claim: str) -> dict[str, str]:
    token, _ = create_access_token(user_id=user_id, role=role_claim)
    return {"Authorization": f"Bearer {token}"}


def test_protected_api_rejects_missing_and_invalid_bearer_tokens(auth_client):
    client, _, _ = auth_client

    missing = client.get("/api/v1/auth/me")
    invalid = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer definitely-not-a-jwt"},
    )

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert invalid.status_code == 401


def test_auth_middleware_uses_database_role_not_untrusted_jwt_role_claim(auth_client):
    client, ids, _ = auth_client

    response = client.get(
        "/api/v1/auth/users",
        headers=bearer(ids["employee_a"], "ADMIN"),
    )

    assert response.status_code == 403


def test_supervisor_can_only_list_users_when_role_is_admin(auth_client):
    client, ids, _ = auth_client

    response = client.get(
        "/api/v1/auth/users",
        headers=bearer(ids["supervisor_a"], "ADMIN"),
    )

    assert response.status_code == 403


def test_employee_cannot_create_store_even_with_admin_role_claim(auth_client):
    client, ids, _ = auth_client

    response = client.post(
        "/api/v1/stores",
        json={"code": "UNAUTHORIZED", "name": "Unauthorized Store"},
        headers=bearer(ids["employee_a"], "ADMIN"),
    )

    assert response.status_code == 403


def test_admin_can_list_users_with_real_database_backed_jwt(auth_client):
    client, ids, _ = auth_client

    response = client.get(
        "/api/v1/auth/users",
        headers=bearer(ids["admin"], "ADMIN"),
    )

    assert response.status_code == 200
    assert {row["email"] for row in response.json()} >= {
        "admin@example.test", "supervisor-a@example.test", "employee-a@example.test"
    }


def test_inactive_user_token_is_rejected_even_when_signature_is_valid(auth_client):
    client, ids, _ = auth_client

    response = client.get(
        "/api/v1/auth/me",
        headers=bearer(ids["inactive"], "ADMIN"),
    )

    assert response.status_code == 401


def test_supervisor_store_listing_is_scoped_to_database_assignment(auth_client):
    client, ids, store_ids = auth_client

    response = client.get(
        "/api/v1/stores",
        headers=bearer(ids["supervisor_a"], "EMPLOYEE"),
    )

    assert response.status_code == 200
    assert [store["id"] for store in response.json()] == [store_ids["a"]]



def test_employee_task_list_and_start_are_limited_to_own_assignment(auth_client):
    client, ids, _ = auth_client

    listed = client.get("/api/v1/tasks", headers=bearer(ids["employee_a"], "EMPLOYEE"))
    assert listed.status_code == 200
    assert [task["id"] for task in listed.json()] == [ids["task_a_assigned"]]

    started = client.patch(
        f"/api/v1/tasks/{ids['task_a_assigned']}/status",
        json={"status": "IN_PROGRESS"},
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert started.status_code == 200
    assert started.json()["status"] == "IN_PROGRESS"

    # Employees can update their own assigned tasks but audit history is supervisor/admin-only.
    employee_events = client.get(
        f"/api/v1/tasks/{ids['task_a_assigned']}/events",
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert employee_events.status_code == 403

    supervisor_events = client.get(
        f"/api/v1/tasks/{ids['task_a_assigned']}/events",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert supervisor_events.status_code == 200
    assert supervisor_events.json()[-1]["actor_user_id"] == ids["employee_a"]


def test_employee_cannot_start_unassigned_task_in_same_store(auth_client):
    client, ids, _ = auth_client

    response = client.patch(
        f"/api/v1/tasks/{ids['task_a_unassigned']}/status",
        json={"status": "IN_PROGRESS"},
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )

    assert response.status_code == 403


def test_employee_cannot_cancel_even_own_assigned_task(auth_client):
    client, ids, _ = auth_client

    response = client.patch(
        f"/api/v1/tasks/{ids['task_a_assigned']}/status",
        json={"status": "CANCELLED", "exception_reason": "Teste de cancelamento"},
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )

    assert response.status_code == 403


def test_supervisor_cannot_read_task_events_from_another_store(auth_client):
    client, ids, _ = auth_client

    response = client.get(
        f"/api/v1/tasks/{ids['task_b_assigned']}/events",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )

    assert response.status_code == 403


def test_supervisor_cannot_cancel_task_from_another_store(auth_client):
    client, ids, _ = auth_client

    response = client.patch(
        f"/api/v1/tasks/{ids['task_b_assigned']}/status",
        json={"status": "CANCELLED", "exception_reason": "Tentativa cross-store"},
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )

    assert response.status_code == 403



def test_employee_cannot_update_task_assigned_to_another_employee_in_same_store(auth_client):
    client, ids, _ = auth_client

    response = client.patch(
        f"/api/v1/tasks/{ids['task_a_peer']}/status",
        json={"status": "IN_PROGRESS"},
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )

    assert response.status_code == 403
