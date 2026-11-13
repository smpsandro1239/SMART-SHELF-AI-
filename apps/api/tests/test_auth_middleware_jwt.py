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
            "supervisor_a_peer": User(
                email="supervisor-a-peer@example.test", full_name="Supervisor A Peer",
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
        observation_a = models.Observation(
            shelf_id=shelf_a_assigned.id, source="simulation", status="LOW_STOCK",
            confidence=0.9, observed_quantity=2,
        )
        observation_b = models.Observation(
            shelf_id=shelf_b.id, source="simulation", status="EMPTY",
            confidence=0.95, observed_quantity=0,
        )
        capture_session_a = models.CaptureSession(
            store_id=store_a.id, shelf_id=shelf_a_assigned.id,
            source_type="mobile", capture_mode="single",
            created_by_user_id=users["supervisor_a"].id,
        )
        capture_session_b = models.CaptureSession(
            store_id=store_b.id, shelf_id=shelf_b.id,
            source_type="mobile", capture_mode="single",
            created_by_user_id=users["employee_b"].id,
        )
        db.add_all([observation_a, observation_b, capture_session_a, capture_session_b])
        db.flush()
        db.add_all([
            models.ShelfProduct(shelf_id=shelf_a_assigned.id, product_id=product.id, target_quantity=10, min_display_quantity=2),
            models.ShelfProduct(shelf_id=shelf_a_unassigned.id, product_id=product.id, target_quantity=10, min_display_quantity=2),
            models.ShelfProduct(shelf_id=shelf_a_peer.id, product_id=product.id, target_quantity=10, min_display_quantity=2),
            models.ShelfProduct(shelf_id=shelf_b.id, product_id=product.id, target_quantity=10, min_display_quantity=2),
        ])
        image_a = models.ShelfImage(
            shelf_id=shelf_a_assigned.id, original_filename="auth-a.jpg",
            storage_path=f"/tmp/{store_a.id}/auth-a.jpg", mime_type="image/jpeg",
            file_size_bytes=10, sha256="d" * 64, analysis_status="PENDING",
            retention_status="ACTIVE",
        )
        image_b = models.ShelfImage(
            shelf_id=shelf_b.id, original_filename="auth-b.jpg",
            storage_path=f"/tmp/{store_b.id}/auth-b.jpg", mime_type="image/jpeg",
            file_size_bytes=10, sha256="e" * 64, analysis_status="PENDING",
            retention_status="RESTRICTED",
        )
        db.add_all([image_a, image_b])
        db.flush()
        embedding_exemplar_a = models.ProductEmbeddingExemplar(
            product_id=product.id,
            shelf_image_id=image_a.id,
            embedding=[0.25, 0.5, 0.75],
            embedding_dimension=3,
            model_version="auth-embedding-v1",
            image_sha256="d" * 64,
            licence="store-owned-reference-image",
            review_status="PENDING",
            created_by_user_id=users["supervisor_a"].id,
        )
        embedding_exemplar_admin = models.ProductEmbeddingExemplar(
            product_id=product.id,
            shelf_image_id=image_a.id,
            embedding=[0.5, 0.75, 0.25],
            embedding_dimension=3,
            model_version="auth-embedding-admin-v1",
            image_sha256="d" * 64,
            licence="store-owned-reference-image",
            review_status="PENDING",
            created_by_user_id=users["supervisor_a"].id,
        )
        detection_a = models.ShelfImageDetection(
            shelf_image_id=image_a.id, product_id=product.id, label="produto",
            confidence=0.95, x_min=0.1, y_min=0.1, x_max=0.5, y_max=0.5,
            model_version="auth-detector-v1",
        )
        detection_b = models.ShelfImageDetection(
            shelf_image_id=image_b.id, product_id=product.id, label="produto",
            confidence=0.95, x_min=0.1, y_min=0.1, x_max=0.5, y_max=0.5,
            model_version="auth-detector-v1",
        )
        db.add_all([embedding_exemplar_a, embedding_exemplar_admin, detection_a, detection_b])
        db.flush()
        db.add(models.ShelfImageRetentionEvent(
            shelf_image_id=image_b.id, event_type="RESTRICTED",
            from_status="ACTIVE", to_status="RESTRICTED",
            reason="Pedido de privacidade",
        ))
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
        ids["image_a"] = image_a.id
        ids["image_b"] = image_b.id
        ids["embedding_exemplar_a"] = embedding_exemplar_a.id
        ids["embedding_exemplar_admin"] = embedding_exemplar_admin.id
        ids["detection_a"] = detection_a.id
        ids["detection_b"] = detection_b.id
        ids["observation_a"] = observation_a.id
        ids["observation_b"] = observation_b.id
        ids["capture_session_a"] = capture_session_a.id
        ids["capture_session_b"] = capture_session_b.id
        ids["shelf_a_assigned"] = shelf_a_assigned.id
        ids["shelf_b"] = shelf_b.id
        store_ids = {"a": store_a.id, "b": store_b.id}
        ids["product"] = product.id

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



def test_supervisor_cannot_create_tasks_for_another_store_through_any_creation_flow(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    foreign_payload = {
        "store_id": store_ids["b"],
        "shelf_id": 999999,
        "product_id": 999999,
        "requested_quantity": 2,
    }

    manual = client.post("/api/v1/tasks", json=foreign_payload, headers=headers)
    recommendation = client.post(
        "/api/v1/tasks/from-recommendation",
        json=foreign_payload,
        headers=headers,
    )
    operational_decision = client.post(
        "/api/v1/tasks/from-operational-decision?approved=true",
        json=foreign_payload,
        headers=headers,
    )

    assert manual.status_code == 403
    assert recommendation.status_code == 403
    assert operational_decision.status_code == 403


def test_employee_cannot_create_task_from_operational_decision(auth_client):
    client, ids, store_ids = auth_client
    response = client.post(
        "/api/v1/tasks/from-operational-decision?approved=true",
        json={
            "store_id": store_ids["a"],
            "shelf_id": 999999,
            "product_id": 999999,
            "requested_quantity": 1,
        },
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )

    assert response.status_code == 403


def test_employee_cannot_reconcile_inventory_even_for_own_store(auth_client):
    client, ids, _ = auth_client
    response = client.post(
        f"/api/v1/tasks/{ids['task_a_assigned']}/reconcile-inventory",
        json={"reason": "Tentativa de reconciliação por funcionário"},
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )

    assert response.status_code == 403


def test_supervisor_cannot_reconcile_task_from_another_store(auth_client):
    client, ids, _ = auth_client
    response = client.post(
        f"/api/v1/tasks/{ids['task_b_assigned']}/reconcile-inventory",
        json={"reason": "Tentativa de reconciliação cross-store"},
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )

    assert response.status_code == 403


def test_employee_cannot_read_or_mutate_shelf_image_retention(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")

    history = client.get(
        f"/api/v1/shelf-images/{ids['image_a']}/retention/events",
        headers=headers,
    )
    restrict = client.post(
        f"/api/v1/shelf-images/{ids['image_a']}/retention/restrict",
        json={"reason": "Pedido do utilizador"},
        headers=headers,
    )

    assert history.status_code == 403
    assert restrict.status_code == 403


def test_supervisor_cannot_apply_or_release_legal_hold(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    apply = client.post(
        f"/api/v1/shelf-images/{ids['image_a']}/retention/legal-hold/apply",
        json={"reason": "Investigação formal"},
        headers=headers,
    )
    release = client.post(
        f"/api/v1/shelf-images/{ids['image_a']}/retention/legal-hold/release",
        json={"reason": "Investigação concluída"},
        headers=headers,
    )

    assert apply.status_code == 403
    assert release.status_code == 403


def test_supervisor_cannot_access_foreign_store_retention_history_or_restrict_image(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    history = client.get(
        f"/api/v1/shelf-images/{ids['image_b']}/retention/events",
        headers=headers,
    )
    restrict = client.post(
        f"/api/v1/shelf-images/{ids['image_b']}/retention/restrict",
        json={"reason": "Pedido do utilizador"},
        headers=headers,
    )

    assert history.status_code == 403
    assert restrict.status_code == 403


def test_supervisor_can_restrict_image_in_own_store_with_audit_event(auth_client):
    client, ids, _ = auth_client

    response = client.post(
        f"/api/v1/shelf-images/{ids['image_a']}/retention/restrict",
        json={"reason": "Pedido do utilizador"},
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )

    assert response.status_code == 200
    assert response.json()["retention_status"] == "RESTRICTED"
    history = client.get(
        f"/api/v1/shelf-images/{ids['image_a']}/retention/events",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert history.status_code == 200
    assert history.json()[-1]["event_type"] == "RESTRICTED"


def test_supervisor_dashboard_summary_is_limited_to_own_store(auth_client):
    client, ids, store_ids = auth_client

    own_store = client.get(
        f"/api/v1/dashboard/summary?store_id={store_ids['a']}",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    foreign_store = client.get(
        f"/api/v1/dashboard/summary?store_id={store_ids['b']}",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )

    assert own_store.status_code == 200
    assert own_store.json()["store_id"] == store_ids["a"]
    assert foreign_store.status_code == 403


def test_supervisor_operational_decisions_are_limited_to_own_store(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    own_store = client.get("/api/v1/operational-decisions", headers=headers)
    foreign_store = client.get(
        f"/api/v1/operational-decisions?store_id={store_ids['b']}",
        headers=headers,
    )

    assert own_store.status_code == 200
    assert all(
        item["store_id"] == store_ids["a"]
        for item in own_store.json()["decisions"]
    )
    assert foreign_store.status_code == 403


def test_employee_cannot_access_team_analytics_or_operational_decisions(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")

    decisions = client.get("/api/v1/operational-decisions", headers=headers)
    workload = client.get(
        f"/api/v1/replenishment/workload?store_id={store_ids['a']}",
        headers=headers,
    )

    assert decisions.status_code == 403
    assert workload.status_code == 403


def test_supervisor_observations_are_scoped_to_own_store(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    own = client.get("/api/v1/observations", headers=headers)
    foreign_filter = client.get(
        "/api/v1/observations",
        params={"shelf_id": ids["shelf_b"]},
        headers=headers,
    )
    foreign_create = client.post(
        "/api/v1/observations",
        json={"shelf_id": ids["shelf_b"], "source": "simulation", "status": "EMPTY"},
        headers=headers,
    )

    assert all(row["shelf_id"] != ids["shelf_b"] for row in own.json())
    assert foreign_filter.status_code == 200
    assert foreign_filter.json() == []
    assert foreign_create.status_code == 403


def test_supervisor_capture_sessions_are_scoped_to_own_store(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    listed = client.get("/api/v1/capture-sessions", headers=headers)
    foreign_create = client.post(
        "/api/v1/capture-sessions",
        json={"shelf_id": ids["shelf_b"], "source_type": "mobile"},
        headers=headers,
    )
    foreign_close = client.post(
        f"/api/v1/capture-sessions/{ids['capture_session_b']}/close",
        headers=headers,
    )

    assert listed.status_code == 200
    assert all(item["store_id"] == store_ids["a"] for item in listed.json())
    assert foreign_create.status_code == 403
    assert foreign_close.status_code == 403


def test_employee_cannot_create_or_close_capture_sessions(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")

    create = client.post(
        "/api/v1/capture-sessions",
        json={"shelf_id": ids["shelf_a_assigned"], "source_type": "mobile"},
        headers=headers,
    )
    close = client.post(
        f"/api/v1/capture-sessions/{ids['capture_session_a']}/close",
        headers=headers,
    )

    assert create.status_code == 403
    assert close.status_code == 403



def test_supervisor_cannot_submit_mixed_store_hourly_sales_batch(auth_client):
    client, ids, store_ids = auth_client
    payload = {
        "records": [
            {
                "store_id": store_ids["a"],
                "product_id": ids["product"],
                "business_date": "2026-11-13",
                "hour_of_day": 9,
                "quantity": 4,
                "source": "POS",
                "external_reference": "AUTH-SALES-A",
            },
            {
                "store_id": store_ids["b"],
                "product_id": ids["product"],
                "business_date": "2026-11-13",
                "hour_of_day": 10,
                "quantity": 7,
                "source": "POS",
                "external_reference": "AUTH-SALES-B",
            },
        ]
    }

    response = client.post(
        "/api/v1/sales/hourly/batch",
        json=payload,
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )

    assert response.status_code == 422
    assert "exactly one store" in response.text


def test_supervisor_cannot_submit_mixed_store_hourly_traffic_batch(auth_client):
    client, ids, store_ids = auth_client
    payload = {
        "records": [
            {
                "store_id": store_ids["a"],
                "business_date": "2026-11-13",
                "hour_of_day": 9,
                "customer_count": 12,
                "source": "POS",
                "external_reference": "AUTH-TRAFFIC-A",
            },
            {
                "store_id": store_ids["b"],
                "business_date": "2026-11-13",
                "hour_of_day": 10,
                "customer_count": 18,
                "source": "POS",
                "external_reference": "AUTH-TRAFFIC-B",
            },
        ]
    }

    response = client.post(
        "/api/v1/sales/traffic/hourly/batch",
        json=payload,
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )

    assert response.status_code == 422
    assert "exactly one store" in response.text


def test_employee_cannot_import_hourly_sales_or_traffic_batches(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    sales_payload = {
        "records": [{
            "store_id": store_ids["a"],
            "product_id": ids["product"],
            "business_date": "2026-11-13",
            "hour_of_day": 9,
            "quantity": 4,
            "source": "POS",
            "external_reference": "EMPLOYEE-SALES",
        }]
    }
    traffic_payload = {
        "records": [{
            "store_id": store_ids["a"],
            "business_date": "2026-11-13",
            "hour_of_day": 9,
            "customer_count": 12,
            "source": "POS",
            "external_reference": "EMPLOYEE-TRAFFIC",
        }]
    }

    sales = client.post("/api/v1/sales/hourly/batch", json=sales_payload, headers=headers)
    traffic = client.post("/api/v1/sales/traffic/hourly/batch", json=traffic_payload, headers=headers)

    assert sales.status_code == 403
    assert traffic.status_code == 403



def test_supervisor_cannot_self_review_embedding_exemplar_with_real_jwt(auth_client):
    client, ids, _ = auth_client
    path = f"/api/v1/product-embedding-exemplars/{ids['embedding_exemplar_a']}/review"
    payload = {
        "review_status": "APPROVED",
        "review_notes": "Tentativa de autoaprovação",
    }

    self_review = client.patch(
        path,
        json=payload,
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert self_review.status_code == 403

    peer_review = client.patch(
        path,
        json={"review_status": "APPROVED", "review_notes": "Revisão por segundo supervisor"},
        headers=bearer(ids["supervisor_a_peer"], "SUPERVISOR"),
    )
    assert peer_review.status_code == 200
    assert peer_review.json()["review_status"] == "APPROVED"

    admin_path = f"/api/v1/product-embedding-exemplars/{ids['embedding_exemplar_admin']}/review"
    admin_review = client.patch(
        admin_path,
        json={"review_status": "APPROVED", "review_notes": "Revisão administrativa independente"},
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert admin_review.status_code == 200
    assert admin_review.json()["review_status"] == "APPROVED"


def test_supervisor_jwt_cannot_access_foreign_ocr_or_retry_restricted_image(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    foreign_image = ids["image_b"]
    ocr_payload = {"provider": "test-provider", "model_version": "test-v1", "regions": []}

    ocr_runs = client.get(f"/api/v1/shelf-images/{foreign_image}/ocr-runs", headers=headers)
    ocr_create = client.post(
        f"/api/v1/shelf-images/{foreign_image}/ocr-runs",
        json=ocr_payload,
        headers=headers,
    )
    retry = client.post(f"/api/v1/shelf-images/{foreign_image}/retry", headers=headers)
    review = client.post(
        f"/api/v1/shelf-image-detections/{ids['detection_b']}/reviews",
        json={"decision": "REJECTED", "selected_product_id": None},
        headers=headers,
    )

    assert ocr_runs.status_code == 403
    assert ocr_create.status_code == 403
    assert retry.status_code == 403
    assert review.status_code == 403


def test_employee_jwt_cannot_start_ocr_or_submit_human_sku_reviews(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    ocr_create = client.post(
        f"/api/v1/shelf-images/{ids['image_a']}/ocr-runs",
        json={"provider": "test-provider", "model_version": "test-v1", "regions": []},
        headers=headers,
    )
    review = client.post(
        f"/api/v1/shelf-image-detections/{ids['detection_a']}/reviews",
        json={"decision": "REJECTED", "selected_product_id": None},
        headers=headers,
    )

    assert ocr_create.status_code == 403
    assert review.status_code == 403
