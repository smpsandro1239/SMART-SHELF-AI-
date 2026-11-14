import pytest
import re
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
        warehouse_location_b = models.WarehouseLocation(
            store_id=store_b.id,
            code="B-WAREHOUSE-01",
            aisle="B",
            rack="01",
            bin_code="01",
            distance_to_picking_m=12,
            max_volume_cm3=100000,
            max_weight_kg=100,
        )
        db.add(warehouse_location_b)
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
        ids["warehouse_location_b"] = warehouse_location_b.id

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


def test_employee_image_list_is_scoped_and_excludes_restricted_images(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")

    # Activate the foreign image so tenant isolation is tested independently
    # from the retention-status filter.
    with main_module.SessionLocal() as db:
        foreign_image = db.get(models.ShelfImage, ids["image_b"])
        assert foreign_image is not None
        foreign_image.retention_status = "ACTIVE"
        db.commit()

    response = client.get("/api/v1/shelf-images", headers=headers)
    assert response.status_code == 200, response.text
    listed_ids = {item["id"] for item in response.json()}
    assert ids["image_a"] in listed_ids
    assert ids["image_b"] not in listed_ids

    # A restricted image in the employee's own store must also disappear.
    with main_module.SessionLocal() as db:
        own_image = db.get(models.ShelfImage, ids["image_a"])
        assert own_image is not None
        own_image.retention_status = "RESTRICTED"
        db.commit()

    restricted_response = client.get("/api/v1/shelf-images", headers=headers)
    assert restricted_response.status_code == 200, restricted_response.text
    restricted_ids = {item["id"] for item in restricted_response.json()}
    assert ids["image_a"] not in restricted_ids
    assert ids["image_b"] not in restricted_ids


def test_employee_cannot_upload_image_to_foreign_store_shelf(
    auth_client, monkeypatch, tmp_path
):
    from io import BytesIO
    from PIL import Image

    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))

    with main_module.SessionLocal() as db:
        before_count = db.query(models.ShelfImage).filter(
            models.ShelfImage.shelf_id == ids["shelf_b"]
        ).count()

    image_bytes = BytesIO()
    Image.new("RGB", (8, 8), (20, 40, 60)).save(image_bytes, format="PNG")
    response = client.post(
        "/api/v1/shelf-images",
        data={"shelf_id": str(ids["shelf_b"])},
        files={"image": ("foreign.png", image_bytes.getvalue(), "image/png")},
        headers=headers,
    )

    assert response.status_code == 403
    assert not list(tmp_path.rglob("*"))
    with main_module.SessionLocal() as db:
        after_count = db.query(models.ShelfImage).filter(
            models.ShelfImage.shelf_id == ids["shelf_b"]
        ).count()
    assert after_count == before_count


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


def test_supervisor_cannot_access_foreign_retention_or_use_admin_restore(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    admin_headers = bearer(ids["admin"], "ADMIN")
    image_id = ids["image_b"]

    history = client.get(
        f"/api/v1/shelf-images/{image_id}/retention/events",
        headers=headers,
    )
    restrict = client.post(
        f"/api/v1/shelf-images/{image_id}/retention/restrict",
        json={"reason": "Tentativa de restrição cross-store"},
        headers=headers,
    )
    restore = client.post(
        f"/api/v1/shelf-images/{image_id}/retention/restore",
        json={"reason": "Tentativa de restauro cross-store"},
        headers=headers,
    )

    assert history.status_code == 403
    assert restrict.status_code == 403
    assert restore.status_code == 403

    admin_history = client.get(
        f"/api/v1/shelf-images/{image_id}/retention/events",
        headers=admin_headers,
    )
    assert admin_history.status_code == 200
    assert [event["event_type"] for event in admin_history.json()] == ["RESTRICTED"]
    assert admin_history.json()[0]["reason"] == "Pedido de privacidade"


def test_supervisor_cannot_restore_restricted_image_even_in_own_store(auth_client):
    client, ids, _ = auth_client
    admin_headers = bearer(ids["admin"], "ADMIN")
    supervisor_headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    image_id = ids["image_a"]
    base = f"/api/v1/shelf-images/{image_id}/retention"

    restricted = client.post(
        f"{base}/restrict",
        json={"reason": "Restrição administrativa para validar o limite de função"},
        headers=admin_headers,
    )
    assert restricted.status_code == 200, restricted.text
    assert restricted.json()["retention_status"] == "RESTRICTED"

    restore = client.post(
        f"{base}/restore",
        json={"reason": "Tentativa de restauro por supervisor da própria loja"},
        headers=supervisor_headers,
    )
    assert restore.status_code == 403, restore.text

    history = client.get(f"{base}/events", headers=admin_headers)
    assert history.status_code == 200, history.text
    assert [event["event_type"] for event in history.json()] == ["RESTRICTED"]
    assert history.json()[0]["reason"] == "Restrição administrativa para validar o limite de função"


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

    def foreign_derived_data_counts():
        with main_module.SessionLocal() as db:
            run_ids = select(models.ShelfImageOCRRun.id).where(
                models.ShelfImageOCRRun.shelf_image_id == foreign_image
            )
            detection_ids = select(models.ShelfImageDetection.id).where(
                models.ShelfImageDetection.shelf_image_id == foreign_image
            )
            return {
                "ocr_runs": db.query(models.ShelfImageOCRRun).filter(
                    models.ShelfImageOCRRun.shelf_image_id == foreign_image
                ).count(),
                "ocr_evidence": db.query(models.ShelfImageOCREvidence).filter(
                    models.ShelfImageOCREvidence.run_id.in_(run_ids)
                ).count(),
                "ocr_matches": db.query(models.ShelfImageOCRMatch).filter(
                    models.ShelfImageOCRMatch.run_id.in_(run_ids)
                ).count(),
                "fused_evidence": db.query(models.ShelfImageFusedEvidence).filter(
                    models.ShelfImageFusedEvidence.ocr_run_id.in_(run_ids)
                ).count(),
                "human_reviews": db.query(models.DetectionSkuReview).filter(
                    models.DetectionSkuReview.detection_id.in_(detection_ids)
                ).count(),
            }

    before = foreign_derived_data_counts()
    requests = {
        "OCR runs": client.get(f"/api/v1/shelf-images/{foreign_image}/ocr-runs", headers=headers),
        "OCR evidence": client.get(f"/api/v1/shelf-images/{foreign_image}/ocr-evidence", headers=headers),
        "OCR matches": client.get(f"/api/v1/shelf-images/{foreign_image}/ocr-matches", headers=headers),
        "fused evidence": client.get(f"/api/v1/shelf-images/{foreign_image}/evidence-fusion", headers=headers),
        "detections": client.get(f"/api/v1/shelf-images/{foreign_image}/detections", headers=headers),
        "binary content": client.get(f"/api/v1/shelf-images/{foreign_image}/content", headers=headers),
        "human review history": client.get(
            f"/api/v1/shelf-image-detections/{ids['detection_b']}/reviews",
            headers=headers,
        ),
        "OCR creation": client.post(
            f"/api/v1/shelf-images/{foreign_image}/ocr-runs",
            json=ocr_payload,
            headers=headers,
        ),
        "OCR matching/persistence": client.post(
            f"/api/v1/shelf-images/{foreign_image}/ocr-matches",
            headers=headers,
        ),
        "visual/OCR fusion persistence": client.post(
            f"/api/v1/shelf-images/{foreign_image}/evidence-fusion",
            headers=headers,
        ),
        "analysis retry": client.post(
            f"/api/v1/shelf-images/{foreign_image}/retry",
            headers=headers,
        ),
        "human review write": client.post(
            f"/api/v1/shelf-image-detections/{ids['detection_b']}/reviews",
            json={"decision": "REJECTED", "selected_product_id": None},
            headers=headers,
        ),
    }
    for resource, response in requests.items():
        assert response.status_code == 403, (
            f"SUPERVISOR must not access foreign {resource}; "
            f"received HTTP {response.status_code}: {response.text}"
        )

    # Explicit shelf filters must not disclose whether a foreign image exists.
    foreign_listing = client.get(
        f"/api/v1/shelf-images?shelf_id={ids['shelf_b']}",
        headers=headers,
    )
    assert foreign_listing.status_code == 200
    assert foreign_listing.json() == []

    # Rejected reads/writes must not create OCR, fusion, or human-review records.
    assert foreign_derived_data_counts() == before


def test_employee_jwt_cannot_start_ocr_or_submit_human_sku_reviews(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    image_url = f"/api/v1/shelf-images/{ids['image_a']}"
    ocr_create = client.post(
        f"{image_url}/ocr-runs",
        json={"provider": "test-provider", "model_version": "test-v1", "regions": []},
        headers=headers,
    )
    ocr_match = client.post(f"{image_url}/ocr-matches", headers=headers)
    evidence_fusion = client.post(f"{image_url}/evidence-fusion", headers=headers)
    review = client.post(
        f"/api/v1/shelf-image-detections/{ids['detection_a']}/reviews",
        json={"decision": "REJECTED", "selected_product_id": None},
        headers=headers,
    )

    assert ocr_create.status_code == 403
    assert ocr_match.status_code == 403
    assert evidence_fusion.status_code == 403
    assert review.status_code == 403



def test_observation_alert_jwt_roles_and_store_scope(auth_client):
    client, ids, store_ids = auth_client

    # Seed confirmed SKU-attributed evidence in both stores using the fixture DB.
    with main_module.SessionLocal() as db:
        now = datetime.now(timezone.utc)
        for shelf_id in (ids["shelf_a_assigned"], ids["shelf_b"]):
            db.add_all([
                models.Observation(
                    shelf_id=shelf_id,
                    product_id=ids["product"],
                    source="simulation",
                    status="LOW_STOCK",
                    confidence=0.95,
                    observed_at=now - timedelta(seconds=seconds_ago),
                )
                for seconds_ago in (60, 40, 20)
            ])
        db.commit()

    params_a = {
        "product_id": ids["product"],
        "minimum_confirmations": 3,
        "minimum_interval_seconds": 10,
        "minimum_confidence": 0.6,
    }
    params_b = dict(params_a)

    own_alert = client.post(
        f"/api/v1/shelves/{ids['shelf_a_assigned']}/observation-alerts/evaluate",
        params=params_a,
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert own_alert.status_code == 200, own_alert.text
    assert own_alert.json()["store_id"] == store_ids["a"]

    foreign_evaluation = client.post(
        f"/api/v1/shelves/{ids['shelf_b']}/observation-alerts/evaluate",
        params=params_b,
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert foreign_evaluation.status_code == 403

    foreign_alert = client.post(
        f"/api/v1/shelves/{ids['shelf_b']}/observation-alerts/evaluate",
        params=params_b,
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert foreign_alert.status_code == 200, foreign_alert.text
    assert foreign_alert.json()["store_id"] == store_ids["b"]

    supervisor_list = client.get(
        "/api/v1/observation-alerts",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    admin_list = client.get(
        "/api/v1/observation-alerts",
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert supervisor_list.status_code == 200
    assert [alert["store_id"] for alert in supervisor_list.json()] == [store_ids["a"]]
    assert admin_list.status_code == 200
    assert {alert["store_id"] for alert in admin_list.json()} == {
        store_ids["a"], store_ids["b"]
    }

    alert_id = own_alert.json()["id"]
    employee_headers = bearer(ids["employee_a"], "EMPLOYEE")
    employee_list = client.get("/api/v1/observation-alerts", headers=employee_headers)
    employee_evaluate = client.post(
        f"/api/v1/shelves/{ids['shelf_a_assigned']}/observation-alerts/evaluate",
        params=params_a,
        headers=employee_headers,
    )
    employee_update = client.patch(
        f"/api/v1/observation-alerts/{alert_id}",
        json={"status": "ACKNOWLEDGED"},
        headers=employee_headers,
    )
    employee_events = client.get(
        f"/api/v1/observation-alerts/{alert_id}/events",
        headers=employee_headers,
    )
    assert employee_list.status_code == 403
    assert employee_evaluate.status_code == 403
    assert employee_update.status_code == 403
    assert employee_events.status_code == 403

    peer_events = client.get(
        f"/api/v1/observation-alerts/{alert_id}/events",
        headers=bearer(ids["supervisor_a_peer"], "SUPERVISOR"),
    )
    assert peer_events.status_code == 200
    assert [event["event_type"] for event in peer_events.json()] == ["CREATED"]
    foreign_alert_id = foreign_alert.json()["id"]
    foreign_update = client.patch(
        f"/api/v1/observation-alerts/{foreign_alert_id}",
        json={"status": "ACKNOWLEDGED"},
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    foreign_events = client.get(
        f"/api/v1/observation-alerts/{foreign_alert_id}/events",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert foreign_update.status_code == 403
    assert foreign_events.status_code == 403

    own_update = client.patch(
        f"/api/v1/observation-alerts/{alert_id}",
        json={"status": "ACKNOWLEDGED"},
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert own_update.status_code == 200, own_update.text
    assert own_update.json()["status"] == "ACKNOWLEDGED"
    own_events_after_update = client.get(
        f"/api/v1/observation-alerts/{alert_id}/events",
        headers=bearer(ids["supervisor_a_peer"], "SUPERVISOR"),
    )
    assert own_events_after_update.status_code == 200
    assert [event["event_type"] for event in own_events_after_update.json()] == [
        "CREATED", "ACKNOWLEDGED"
    ]

    foreign_admin_events = client.get(
        f"/api/v1/observation-alerts/{foreign_alert_id}/events",
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert foreign_admin_events.status_code == 200
    assert [event["event_type"] for event in foreign_admin_events.json()] == ["CREATED"]



def test_employee_jwt_completion_requires_valid_quantity_and_partial_reason(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    task_id = ids["task_a_assigned"]
    path = f"/api/v1/tasks/{task_id}/status"

    started = client.patch(path, json={"status": "IN_PROGRESS"}, headers=headers)
    assert started.status_code == 200, started.text

    excessive = client.patch(
        path,
        json={"status": "COMPLETED", "actual_quantity": 6},
        headers=headers,
    )
    assert excessive.status_code == 409
    assert excessive.json()["detail"]["code"] == "ACTUAL_QUANTITY_EXCEEDS_REQUESTED"

    missing_partial_reason = client.patch(
        path,
        json={"status": "COMPLETED", "actual_quantity": 3},
        headers=headers,
    )
    assert missing_partial_reason.status_code == 422
    assert missing_partial_reason.json()["detail"]["code"] == "PARTIAL_COMPLETION_REASON_REQUIRED"

    completed = client.patch(
        path,
        json={
            "status": "COMPLETED",
            "actual_quantity": 3,
            "exception_reason": "Faltaram duas unidades na retaguarda",
        },
        headers=headers,
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json()["actual_quantity"] == 3
    assert completed.json()["exception_reason"] == "Faltaram duas unidades na retaguarda"

    supervisor_events = client.get(
        f"/api/v1/tasks/{task_id}/events",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert supervisor_events.status_code == 200
    assert [event["event_type"] for event in supervisor_events.json()] == [
        "CREATED", "STATUS_CHANGED", "STATUS_CHANGED"
    ]
    assert supervisor_events.json()[-1]["actual_quantity"] == 3
    assert supervisor_events.json()[-1]["reason"] == "Faltaram duas unidades na retaguarda"


def test_employee_jwt_cannot_reassign_task_while_starting_it(auth_client):
    client, ids, _ = auth_client
    response = client.patch(
        f"/api/v1/tasks/{ids['task_a_assigned']}/status",
        json={
            "status": "IN_PROGRESS",
            "assigned_user_id": ids["employee_a_peer"],
        },
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert response.status_code == 403



def test_every_versioned_api_route_requires_bearer_except_public_auth_routes(auth_client):
    client, _, _ = auth_client
    public_paths = {"/api/v1/auth/bootstrap", "/api/v1/auth/login"}
    checked = set()

    for route in main_module.app.routes:
        path_template = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if not path_template.startswith("/api/v1/"):
            continue
        path = re.sub(r"\{[^}]+\}", "1", path_template)
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            key = (method, path_template)
            if key in checked or path_template in public_paths:
                continue
            checked.add(key)
            response = client.request(method, path)
            assert response.status_code == 401, (
                f"{method} {path_template} must require Bearer authentication; "
                f"received HTTP {response.status_code}"
            )

    assert checked, "The test must inspect at least one protected versioned API route"

@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/users",
        "/api/v1/stores",
        "/api/v1/zones",
        "/api/v1/shelves",
        "/api/v1/products",
        "/api/v1/shelf-products",
        "/api/v1/warehouse/product-profiles",
        "/api/v1/warehouse/product-packaging",
    ],
)
def test_admin_only_creation_routes_reject_non_admin_roles_before_handler(
    auth_client, path
):
    client, ids, _ = auth_client

    for user_key, role in (
        ("supervisor_a", "SUPERVISOR"),
        ("employee_a", "EMPLOYEE"),
    ):
        response = client.post(
            path,
            json={},
            headers=bearer(ids[user_key], role),
        )
        assert response.status_code == 403, (
            f"{role} must not invoke admin-only endpoint {path}; "
            f"received HTTP {response.status_code}"
        )

    admin_response = client.post(
        path,
        json={},
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert admin_response.status_code == 422, (
        f"ADMIN must pass the role gate for {path}; "
        "the empty payload should be rejected by request validation"
    )

def test_employee_jwt_cannot_read_foreign_image_derived_data_or_content(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    foreign_image_id = ids["image_b"]
    foreign_detection_id = ids["detection_b"]

    requests = {
        "binary content": client.get(
            f"/api/v1/shelf-images/{foreign_image_id}/content",
            headers=headers,
        ),
        "detections": client.get(
            f"/api/v1/shelf-images/{foreign_image_id}/detections",
            headers=headers,
        ),
        "OCR evidence": client.get(
            f"/api/v1/shelf-images/{foreign_image_id}/ocr-evidence",
            headers=headers,
        ),
        "OCR runs": client.get(
            f"/api/v1/shelf-images/{foreign_image_id}/ocr-runs",
            headers=headers,
        ),
        "OCR matches": client.get(
            f"/api/v1/shelf-images/{foreign_image_id}/ocr-matches",
            headers=headers,
        ),
        "fused evidence": client.get(
            f"/api/v1/shelf-images/{foreign_image_id}/evidence-fusion",
            headers=headers,
        ),
        "human review history": client.get(
            f"/api/v1/shelf-image-detections/{foreign_detection_id}/reviews",
            headers=headers,
        ),
    }

    for resource, response in requests.items():
        assert response.status_code == 403, (
            f"EMPLOYEE must not access foreign {resource}; "
            f"received HTTP {response.status_code}: {response.text}"
        )

@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/api/v1/sales/daily"),
        ("POST", "/api/v1/sales/import-csv"),
        ("POST", "/api/v1/sales/hourly"),
        ("POST", "/api/v1/sales/traffic/hourly"),
        ("POST", "/api/v1/sales/hourly/import-csv"),
        ("POST", "/api/v1/sales/traffic/hourly/import-csv"),
        ("POST", "/api/v1/warehouse/locations"),
        ("POST", "/api/v1/warehouse/placements"),
        ("POST", "/api/v1/warehouse/pallets"),
        ("POST", "/api/v1/warehouse/pallet-rotation/policies"),
        ("PATCH", "/api/v1/warehouse/pallet-rotation/policies/999999"),
        ("POST", "/api/v1/warehouse/pallet-rotation/simulate"),
        ("POST", "/api/v1/warehouse/pallets/999999/events"),
    ],
)
def test_employee_cannot_use_supervisor_managed_write_endpoints(
    auth_client, method, path
):
    client, ids, _ = auth_client
    response = client.request(
        method,
        path,
        json={},
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )

    assert response.status_code == 403, (
        f"EMPLOYEE must not invoke supervisor-managed endpoint {method} {path}; "
        f"received HTTP {response.status_code}: {response.text}"
    )

def test_supervisor_jwt_cannot_access_foreign_warehouse_resources(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    foreign_store_id = store_ids["b"]

    requests = {
        "warehouse locations": client.get(
            "/api/v1/warehouse/locations",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
        "registered pallets": client.get(
            "/api/v1/warehouse/pallets",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
        "pallet rotation policies": client.get(
            "/api/v1/warehouse/pallet-rotation/policies",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
        "warehouse location creation": client.post(
            "/api/v1/warehouse/locations",
            json={
                "store_id": foreign_store_id,
                "code": "FOREIGN-LOCATION",
                "distance_to_picking_m": 12,
                "max_volume_cm3": 100000,
                "max_weight_kg": 100,
            },
            headers=headers,
        ),
        "pallet registration": client.post(
            "/api/v1/warehouse/pallets",
            json={
                "store_id": foreign_store_id,
                "product_id": ids["product"],
                "packaging_level_id": 999999,
                "pallet_code": "FOREIGN-PALLET",
                "base_quantity": 10,
                "status": "READY",
                "location_type": "WAREHOUSE",
            },
            headers=headers,
        ),
        "pallet rotation policy creation": client.post(
            "/api/v1/warehouse/pallet-rotation/policies",
            json={
                "store_id": foreign_store_id,
                "product_id": ids["product"],
                "threshold_ratio": 0.5,
                "is_enabled": True,
            },
            headers=headers,
        ),
        "pallet rotation simulation": client.post(
            "/api/v1/warehouse/pallet-rotation/simulate",
            json={
                "store_id": foreign_store_id,
                "pallet_id": 999999,
                "traffic_level": "UNKNOWN",
                "backroom_capacity_available": True,
                "conventional_replenishment_minutes": 10,
                "pallet_swap_minutes": 8,
                "transport_minutes": 2,
                "pallet_rebuild_minutes": 5,
                "labour_cost_per_hour": 12,
                "forecast_consumption_until_low_traffic": 0,
            },
            headers=headers,
        ),
    }

    for resource, response in requests.items():
        assert response.status_code == 403, (
            f"SUPERVISOR must not access foreign {resource}; "
            f"received HTTP {response.status_code}: {response.text}"
        )

    # A denied cross-store write must not leave partial state behind.
    admin_headers = bearer(ids["admin"], "ADMIN")
    foreign_snapshots = client.get(
        "/api/v1/inventory/snapshots",
        params={"store_id": foreign_store_id},
        headers=admin_headers,
    )
    assert foreign_snapshots.status_code == 200
    assert foreign_snapshots.json() == []

    foreign_freshness_policies = client.get(
        "/api/v1/inventory/freshness-policies",
        params={"store_id": foreign_store_id},
        headers=admin_headers,
    )
    assert foreign_freshness_policies.status_code == 200
    assert foreign_freshness_policies.json() == []


    
def test_supervisor_jwt_cannot_read_or_write_foreign_inventory_and_placement_resources(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    foreign_store_id = store_ids["b"]

    requests = {
        "inventory snapshot list": client.get(
            "/api/v1/inventory/snapshots",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
        "latest inventory snapshot": client.get(
            "/api/v1/inventory/latest",
            params={"store_id": foreign_store_id, "product_id": ids["product"]},
            headers=headers,
        ),
        "inventory snapshot creation": client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": foreign_store_id,
                "product_id": ids["product"],
                "on_hand_quantity": 24,
                "reserved_quantity": 2,
                "source": "MANUAL",
                "external_reference": "AUTH-FOREIGN-SNAPSHOT",
            },
            headers=headers,
        ),
        "inventory freshness policy list": client.get(
            "/api/v1/inventory/freshness-policies",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
        "inventory freshness policy upsert": client.post(
            "/api/v1/inventory/freshness-policies",
            json={
                "store_id": foreign_store_id,
                "source": "MANUAL",
                "max_age_minutes": 60,
            },
            headers=headers,
        ),
        "warehouse placement creation": client.post(
            "/api/v1/warehouse/placements",
            json={
                "location_id": ids["warehouse_location_b"],
                "product_id": ids["product"],
                "quantity": 5,
            },
            headers=headers,
        ),
        "warehouse slotting recommendations": client.get(
            "/api/v1/warehouse/slotting-recommendations",
            params={"store_id": foreign_store_id, "source": "POS"},
            headers=headers,
        ),
    }

    for resource, response in requests.items():
        assert response.status_code == 403, (
            f"SUPERVISOR must not access foreign {resource}; "
            f"received HTTP {response.status_code}: {response.text}"
        )

def test_supervisor_jwt_cannot_read_foreign_sales_forecasts_or_warehouse_analytics(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    foreign_store_id = store_ids["b"]
    product_id = ids["product"]

    requests = {
        "hourly sales history": client.get(
            "/api/v1/sales/hourly",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
        "hourly traffic history": client.get(
            "/api/v1/sales/traffic/hourly",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
        "daily sales history": client.get(
            "/api/v1/sales/daily",
            params={"store_id": foreign_store_id, "product_id": product_id, "source": "POS"},
            headers=headers,
        ),
        "traffic peak analytics": client.get(
            "/api/v1/forecasting/traffic-peaks",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
        "hourly demand forecast": client.get(
            "/api/v1/forecasting/hourly-demand",
            params={"store_id": foreign_store_id, "product_id": product_id},
            headers=headers,
        ),
        "daily demand forecast": client.get(
            "/api/v1/forecasting/demand",
            params={
                "store_id": foreign_store_id,
                "product_id": product_id,
                "source": "POS",
                "lead_time_days": 2,
            },
            headers=headers,
        ),
        "stockout risk": client.get(
            "/api/v1/forecasting/stockout-risk",
            params={
                "store_id": foreign_store_id,
                "product_id": product_id,
                "source": "POS",
                "lead_time_days": 2,
            },
            headers=headers,
        ),
        "stockout risk portfolio": client.get(
            "/api/v1/forecasting/stockout-risk/portfolio",
            params={
                "store_id": foreign_store_id,
                "source": "POS",
                "lead_time_days": 2,
            },
            headers=headers,
        ),
        "pallet hourly demand profile": client.get(
            "/api/v1/warehouse/pallet-rotation/hourly-profile",
            params={"store_id": foreign_store_id, "product_id": product_id},
            headers=headers,
        ),
        "pallet weekday/hour profile": client.get(
            "/api/v1/warehouse/pallet-rotation/weekday-hourly-profile",
            params={"store_id": foreign_store_id, "product_id": product_id},
            headers=headers,
        ),
        "pallet rotation window plan": client.get(
            "/api/v1/warehouse/pallet-rotation/window-plan",
            params={
                "store_id": foreign_store_id,
                "product_id": product_id,
                "pallet_id": 999999,
                "current_hour": 12,
                "residual_base_units": 1,
            },
            headers=headers,
        ),
        "historical pallet portfolio": client.get(
            "/api/v1/warehouse/pallet-rotation/portfolio-from-history",
            params={"store_id": foreign_store_id, "current_hour": 12},
            headers=headers,
        ),
        "pallet rotation portfolio": client.get(
            "/api/v1/warehouse/pallet-rotation/portfolio",
            params={
                "store_id": foreign_store_id,
                "traffic_level": "UNKNOWN",
                "forecast_consumption_until_low_traffic": 0,
            },
            headers=headers,
        ),
        "pallet lifecycle events": client.get(
            "/api/v1/warehouse/pallets/999999/events",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
        "replenishment pack calculation": client.get(
            "/api/v1/warehouse/replenishment-units",
            params={
                "store_id": foreign_store_id,
                "product_id": product_id,
                "required_base_units": 1,
                "packaging_code": "CASE",
            },
            headers=headers,
        ),
        "physical warehouse slotting": client.get(
            "/api/v1/warehouse/physical-slotting",
            params={
                "store_id": foreign_store_id,
                "product_id": product_id,
                "required_quantity": 1,
            },
            headers=headers,
        ),
        "replenishment recommendations": client.get(
            "/api/v1/replenishment/recommendations",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
        "replenishment plan": client.get(
            "/api/v1/replenishment/plan",
            params={"store_id": foreign_store_id},
            headers=headers,
        ),
    }

    for resource, response in requests.items():
        assert response.status_code == 403, (
            f"SUPERVISOR must not access foreign {resource}; "
            f"received HTTP {response.status_code}: {response.text}"
        )

def test_supervisor_jwt_cannot_write_foreign_sales_or_traffic_records(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    admin_headers = bearer(ids["admin"], "ADMIN")
    foreign_store_id = store_ids["b"]
    product_id = ids["product"]
    business_date = "2026-11-13"

    sales_record = {
        "store_id": foreign_store_id,
        "product_id": product_id,
        "business_date": business_date,
        "hour_of_day": 10,
        "quantity": 3,
        "source": "POS",
        "external_reference": "AUTH-FOREIGN-HOURLY-SALES",
    }
    traffic_record = {
        "store_id": foreign_store_id,
        "business_date": business_date,
        "hour_of_day": 10,
        "customer_count": 12,
        "source": "POS",
        "external_reference": "AUTH-FOREIGN-HOURLY-TRAFFIC",
    }
    daily_record = {
        "store_id": foreign_store_id,
        "product_id": product_id,
        "sales_date": business_date,
        "quantity": 3,
        "source": "POS",
        "external_reference": "AUTH-FOREIGN-DAILY-SALES",
    }

    requests = {
        "daily sales creation": client.post(
            "/api/v1/sales/daily", json=daily_record, headers=headers
        ),
        "hourly sales creation": client.post(
            "/api/v1/sales/hourly", json=sales_record, headers=headers
        ),
        "hourly traffic creation": client.post(
            "/api/v1/sales/traffic/hourly", json=traffic_record, headers=headers
        ),
        "hourly sales batch creation": client.post(
            "/api/v1/sales/hourly/batch",
            json={"records": [sales_record]},
            headers=headers,
        ),
        "hourly traffic batch creation": client.post(
            "/api/v1/sales/traffic/hourly/batch",
            json={"records": [traffic_record]},
            headers=headers,
        ),
    }

    for resource, response in requests.items():
        assert response.status_code == 403, (
            f"SUPERVISOR must not write foreign {resource}; "
            f"received HTTP {response.status_code}: {response.text}"
        )

    daily_rows = client.get(
        "/api/v1/sales/daily",
        params={
            "store_id": foreign_store_id,
            "product_id": product_id,
            "source": "POS",
            "days": 1,
        },
        headers=admin_headers,
    )
    hourly_rows = client.get(
        "/api/v1/sales/hourly",
        params={
            "store_id": foreign_store_id,
            "start_date": business_date,
            "end_date": business_date,
        },
        headers=admin_headers,
    )
    traffic_rows = client.get(
        "/api/v1/sales/traffic/hourly",
        params={
            "store_id": foreign_store_id,
            "start_date": business_date,
            "end_date": business_date,
        },
        headers=admin_headers,
    )

    assert daily_rows.status_code == 200, daily_rows.text
    assert hourly_rows.status_code == 200, hourly_rows.text
    assert traffic_rows.status_code == 200, traffic_rows.text
    assert daily_rows.json() == []
    assert hourly_rows.json() == []
    assert traffic_rows.json() == []

def test_admin_legal_hold_is_idempotent_and_preserves_operational_visibility(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["admin"], "ADMIN")
    image_id = ids["image_a"]
    base = f"/api/v1/shelf-images/{image_id}/retention"

    first_apply = client.post(
        f"{base}/legal-hold/apply",
        json={"reason": "Preservar evidência para investigação"},
        headers=headers,
    )
    repeated_apply = client.post(
        f"{base}/legal-hold/apply",
        json={"reason": "Repetição idempotente do pedido"},
        headers=headers,
    )

    assert first_apply.status_code == 200, first_apply.text
    assert repeated_apply.status_code == 200, repeated_apply.text
    assert first_apply.json()["legal_hold"] is True
    assert repeated_apply.json()["legal_hold"] is True
    assert first_apply.json()["retention_status"] == "ACTIVE"
    assert repeated_apply.json()["retention_status"] == "ACTIVE"

    first_release = client.post(
        f"{base}/legal-hold/release",
        json={"reason": "Investigação concluída e libertação autorizada"},
        headers=headers,
    )
    repeated_release = client.post(
        f"{base}/legal-hold/release",
        json={"reason": "Repetição idempotente da libertação"},
        headers=headers,
    )

    assert first_release.status_code == 200, first_release.text
    assert repeated_release.status_code == 200, repeated_release.text
    assert first_release.json()["legal_hold"] is False
    assert repeated_release.json()["legal_hold"] is False
    assert first_release.json()["retention_status"] == "ACTIVE"
    assert repeated_release.json()["retention_status"] == "ACTIVE"

    history = client.get(f"{base}/events", headers=headers)
    assert history.status_code == 200, history.text
    assert [event["event_type"] for event in history.json()] == [
        "LEGAL_HOLD_APPLIED",
        "LEGAL_HOLD_RELEASED",
    ]
    assert history.json()[0]["reason"] == "Preservar evidência para investigação"
    assert history.json()[1]["reason"] == "Investigação concluída e libertação autorizada"



def test_supervisor_review_queue_and_summary_are_scoped_to_own_store(auth_client):
    client, ids, _ = auth_client

    # Activate the foreign image in this isolated test so tenant filtering,
    # rather than the independent retention filter, is what excludes it.
    with main_module.SessionLocal() as db:
        foreign_image = db.get(models.ShelfImage, ids["image_b"])
        foreign_image.retention_status = "ACTIVE"
        run_a = models.ShelfImageOCRRun(
            shelf_image_id=ids["image_a"], provider="auth-test-provider",
            model_version="auth-test-v1", status="COMPLETED",
        )
        run_b = models.ShelfImageOCRRun(
            shelf_image_id=ids["image_b"], provider="auth-test-provider",
            model_version="auth-test-v1", status="COMPLETED",
        )
        db.add_all([run_a, run_b])
        db.flush()
        evidence_a = models.ShelfImageFusedEvidence(
            ocr_run_id=run_a.id, detection_id=ids["detection_a"],
            status="CONFLICT", visual_status="MATCHED", text_status="SUGGESTED",
            visual_similarity=0.91, text_score=0.82, ocr_confidence=0.88,
            visual_model_version="auth-visual-v1",
            ocr_provider="auth-test-provider", ocr_model_version="auth-test-v1",
            reason="Divergência de teste na loja A",
        )
        evidence_b = models.ShelfImageFusedEvidence(
            ocr_run_id=run_b.id, detection_id=ids["detection_b"],
            status="CONSENSUS", visual_status="MATCHED", text_status="MATCHED",
            visual_similarity=0.96, text_score=0.94, ocr_confidence=0.93,
            visual_model_version="auth-visual-v1",
            ocr_provider="auth-test-provider", ocr_model_version="auth-test-v1",
            reason="Concordância de teste na loja B",
        )
        db.add_all([evidence_a, evidence_b])
        db.commit()
        evidence_a_id, evidence_b_id = evidence_a.id, evidence_b.id

    supervisor_headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    supervisor_queue = client.get(
        "/api/v1/shelf-image-review-queue", headers=supervisor_headers
    )
    supervisor_summary = client.get(
        "/api/v1/shelf-image-review-queue/summary", headers=supervisor_headers
    )
    assert supervisor_queue.status_code == 200, supervisor_queue.text
    assert [item["fused_evidence_id"] for item in supervisor_queue.json()] == [evidence_a_id]
    assert all(item["shelf_image_id"] == ids["image_a"] for item in supervisor_queue.json())
    assert supervisor_summary.status_code == 200, supervisor_summary.text
    assert supervisor_summary.json()["CONFLICT"] == 1
    assert supervisor_summary.json()["CONSENSUS"] == 0
    assert sum(supervisor_summary.json().values()) == 1

    admin_headers = bearer(ids["admin"], "ADMIN")
    admin_queue = client.get(
        "/api/v1/shelf-image-review-queue", headers=admin_headers
    )
    admin_summary = client.get(
        "/api/v1/shelf-image-review-queue/summary", headers=admin_headers
    )
    assert admin_queue.status_code == 200, admin_queue.text
    assert {item["fused_evidence_id"] for item in admin_queue.json()} == {
        evidence_a_id, evidence_b_id
    }
    assert {item["shelf_image_id"] for item in admin_queue.json()} == {
        ids["image_a"], ids["image_b"]
    }
    assert admin_summary.status_code == 200, admin_summary.text
    assert admin_summary.json()["CONFLICT"] == 1
    assert admin_summary.json()["CONSENSUS"] == 1
    assert sum(admin_summary.json().values()) == 2

    employee_headers = bearer(ids["employee_a"], "EMPLOYEE")
    employee_queue = client.get(
        "/api/v1/shelf-image-review-queue", headers=employee_headers
    )
    employee_summary = client.get(
        "/api/v1/shelf-image-review-queue/summary", headers=employee_headers
    )
    assert employee_queue.status_code == 403
    assert employee_summary.status_code == 403

    # Both endpoints are read-only.
    with main_module.SessionLocal() as db:
        assert db.query(models.ShelfImageFusedEvidence).count() == 2
        assert db.get(models.ShelfImageFusedEvidence, evidence_a_id) is not None
        assert db.get(models.ShelfImageFusedEvidence, evidence_b_id) is not None
