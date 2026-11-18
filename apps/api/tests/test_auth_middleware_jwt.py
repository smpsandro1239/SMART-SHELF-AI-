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
        active_packaging = models.ProductPackagingLevel(
            product_id=product.id,
            code="AUTH-CASE",
            name="Caixa de teste",
            package_type="CASE",
            base_units_per_package=12,
            is_active=True,
        )
        inactive_packaging = models.ProductPackagingLevel(
            product_id=product.id,
            code="AUTH-OLD",
            name="Embalagem desativada",
            package_type="CASE",
            base_units_per_package=24,
            is_active=False,
        )
        db.add_all([active_packaging, inactive_packaging])
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
        ids["shelf_a_unassigned"] = shelf_a_unassigned.id
        ids["shelf_a_peer"] = shelf_a_peer.id
        ids["shelf_b"] = shelf_b.id
        store_ids = {"a": store_a.id, "b": store_b.id}
        ids["product"] = product.id
        ids["active_packaging"] = active_packaging.id
        ids["inactive_packaging"] = inactive_packaging.id
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



def test_employee_can_upload_valid_image_to_own_store_capture_session(
    auth_client, monkeypatch, tmp_path
):
    from hashlib import sha256
    from io import BytesIO
    from PIL import Image

    client, ids, store_ids = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))

    image_bytes = BytesIO()
    Image.new("RGB", (12, 10), (35, 75, 115)).save(image_bytes, format="PNG")
    content = image_bytes.getvalue()

    response = client.post(
        "/api/v1/shelf-images",
        data={
            "shelf_id": str(ids["shelf_a_assigned"]),
            "capture_session_id": str(ids["capture_session_a"]),
        },
        files={"image": ("own-capture.png", content, "image/png")},
        headers=headers,
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["original_filename"] == "own-capture.png"
    assert payload["mime_type"] == "image/png"
    assert payload["file_size_bytes"] == len(content)
    assert payload["sha256"] == sha256(content).hexdigest()

    with main_module.SessionLocal() as db:
        stored = db.get(models.ShelfImage, payload["id"])
        assert stored is not None
        assert stored.shelf_id == ids["shelf_a_assigned"]
        assert stored.capture_session_id == ids["capture_session_a"]
        assert stored.uploaded_by == ids["employee_a"]
        assert stored.retention_status == "ACTIVE"
        stored_path = __import__("pathlib").Path(stored.storage_path)
        assert stored_path.parent == tmp_path / str(store_ids["a"])
        assert stored_path.read_bytes() == content

    listed = client.get("/api/v1/shelf-images", headers=headers)
    assert listed.status_code == 200, listed.text
    assert payload["id"] in {item["id"] for item in listed.json()}

def test_employee_cannot_upload_image_with_foreign_capture_session(
    auth_client, monkeypatch, tmp_path
):
    from io import BytesIO
    from PIL import Image

    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))

    with main_module.SessionLocal() as db:
        before_count = db.query(models.ShelfImage).filter(
            models.ShelfImage.shelf_id == ids["shelf_a_assigned"]
        ).count()

    image_bytes = BytesIO()
    Image.new("RGB", (10, 8), (45, 85, 125)).save(image_bytes, format="PNG")
    response = client.post(
        "/api/v1/shelf-images",
        data={
            "shelf_id": str(ids["shelf_a_assigned"]),
            "capture_session_id": str(ids["capture_session_b"]),
        },
        files={"image": ("foreign-session.png", image_bytes.getvalue(), "image/png")},
        headers=headers,
    )

    assert response.status_code == 422, response.text
    assert not list(tmp_path.rglob("*"))
    with main_module.SessionLocal() as db:
        after_count = db.query(models.ShelfImage).filter(
            models.ShelfImage.shelf_id == ids["shelf_a_assigned"]
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
    purge_schedule = client.post(
        f"/api/v1/shelf-images/{image_id}/retention/purge-schedule",
        json={
            "purge_not_before": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
            "policy_version": "auth-test-policy",
            "reason": "Tentativa de agendamento cross-store",
        },
        headers=headers,
    )
    purge_cancel = client.post(
        f"/api/v1/shelf-images/{image_id}/retention/purge-schedule/cancel",
        json={"reason": "Tentativa de cancelamento cross-store"},
        headers=headers,
    )

    assert history.status_code == 403
    assert restrict.status_code == 403
    assert restore.status_code == 403
    assert purge_schedule.status_code == 403
    assert purge_cancel.status_code == 403

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
    own_shelf = client.get(
        "/api/v1/capture-sessions",
        params={"shelf_id": ids["shelf_a_assigned"]},
        headers=headers,
    )
    foreign_shelf = client.get(
        "/api/v1/capture-sessions",
        params={"shelf_id": ids["shelf_b"]},
        headers=headers,
    )
    foreign_create = client.post(
        "/api/v1/capture-sessions",
        json={"shelf_id": ids["shelf_b"], "source_type": "mobile"},
        headers=headers,
    )
    foreign_close = client.post(
        f"/api/v1/capture-sessions/{ids['capture_session_b']}/close",
        headers=headers,
    )
    admin_listed = client.get(
        "/api/v1/capture-sessions",
        headers=bearer(ids["admin"], "ADMIN"),
    )
    employee_listed = client.get(
        "/api/v1/capture-sessions",
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )

    assert listed.status_code == 200
    assert all(item["store_id"] == store_ids["a"] for item in listed.json())
    assert own_shelf.status_code == 200
    assert len(own_shelf.json()) == 1
    assert own_shelf.json()[0]["shelf_id"] == ids["shelf_a_assigned"]
    assert foreign_shelf.status_code == 200
    assert foreign_shelf.json() == []
    assert foreign_create.status_code == 403
    assert foreign_close.status_code == 403
    assert admin_listed.status_code == 200
    assert {item["store_id"] for item in admin_listed.json()} == {
        store_ids["a"], store_ids["b"]
    }
    assert employee_listed.status_code == 403


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


def test_restricted_own_store_image_rejects_ocr_writes_and_retry(auth_client):
    client, ids, _ = auth_client
    admin_headers = bearer(ids["admin"], "ADMIN")
    supervisor_headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    image_id = ids["image_a"]

    with main_module.SessionLocal() as db:
        image = db.get(models.ShelfImage, image_id)
        image.analysis_status = "FAILED"
        db.commit()

    restricted = client.post(
        f"/api/v1/shelf-images/{image_id}/retention/restrict",
        json={"reason": "Auditoria de retenção"},
        headers=admin_headers,
    )
    assert restricted.status_code == 200

    def derived_counts():
        with main_module.SessionLocal() as db:
            run_ids = select(models.ShelfImageOCRRun.id).where(
                models.ShelfImageOCRRun.shelf_image_id == image_id
            )
            return (
                db.query(models.ShelfImageOCRRun).filter(
                    models.ShelfImageOCRRun.shelf_image_id == image_id
                ).count(),
                db.query(models.ShelfImageOCREvidence).filter(
                    models.ShelfImageOCREvidence.run_id.in_(run_ids)
                ).count(),
                db.query(models.ShelfImageOCRMatch).filter(
                    models.ShelfImageOCRMatch.run_id.in_(run_ids)
                ).count(),
            )

    before = derived_counts()
    # Retention restriction must block the original binary and source-linked
    # embedding exemplars, not only OCR writes and analysis retries.
    binary_content = client.get(
        f"/api/v1/shelf-images/{image_id}/content",
        headers=admin_headers,
    )
    exemplar_listing = client.get(
        "/api/v1/product-embedding-exemplars",
        headers=admin_headers,
    )
    assert binary_content.status_code == 410
    assert exemplar_listing.status_code == 200, exemplar_listing.text
    assert all(
        item["shelf_image_id"] != image_id
        for item in exemplar_listing.json()
    )

    ocr_create = client.post(
        f"/api/v1/shelf-images/{image_id}/ocr-runs",
        json={"provider": "test-provider", "model_version": "test-v1", "regions": []},
        headers=supervisor_headers,
    )
    ocr_match = client.post(
        f"/api/v1/shelf-images/{image_id}/ocr-matches",
        headers=supervisor_headers,
    )
    retry = client.post(
        f"/api/v1/shelf-images/{image_id}/retry",
        headers=supervisor_headers,
    )

    assert ocr_create.status_code == 410
    assert ocr_match.status_code == 410
    assert retry.status_code == 410
    assert derived_counts() == before
    with main_module.SessionLocal() as db:
        image = db.get(models.ShelfImage, image_id)
        assert image.retention_status == "RESTRICTED"
        assert image.analysis_status == "FAILED"


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




def test_admin_bootstrap_requires_key_and_rejects_second_initialization(auth_client, monkeypatch):
    client, _, _ = auth_client
    original_settings = main_module.settings
    bootstrap_key = "bootstrap-test-key-that-is-long-enough"
    monkeypatch.setattr(
        main_module,
        "settings",
        original_settings.model_copy(update={"bootstrap_admin_key": bootstrap_key}),
    )

    invalid = client.post(
        "/api/v1/auth/bootstrap",
        headers={"X-Bootstrap-Key": "incorrect"},
        json={
            "email": "unexpected-admin@example.test",
            "full_name": "Unexpected Admin",
            "password": "Strong-password-42!",
        },
    )
    assert invalid.status_code == 403

    already_initialized = client.post(
        "/api/v1/auth/bootstrap",
        headers={"X-Bootstrap-Key": bootstrap_key},
        json={
            "email": "second-admin@example.test",
            "full_name": "Second Admin",
            "password": "Strong-password-42!",
        },
    )
    assert already_initialized.status_code == 409
    assert already_initialized.json()["detail"] == "Administrator bootstrap has already been completed"


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

    first_page = client.get(
        f"{base}/events?limit=1&offset=0",
        headers=headers,
    )
    second_page = client.get(
        f"{base}/events?limit=1&offset=1",
        headers=headers,
    )
    clamped_page = client.get(
        f"{base}/events?limit=0&offset=-10",
        headers=headers,
    )
    assert first_page.status_code == 200, first_page.text
    assert second_page.status_code == 200, second_page.text
    assert clamped_page.status_code == 200, clamped_page.text
    assert [event["event_type"] for event in first_page.json()] == ["LEGAL_HOLD_APPLIED"]
    assert [event["event_type"] for event in second_page.json()] == ["LEGAL_HOLD_RELEASED"]
    assert [event["event_type"] for event in clamped_page.json()] == ["LEGAL_HOLD_APPLIED"]



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


def test_supervisor_can_create_and_close_capture_session_in_own_store(auth_client):
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    created = client.post(
        "/api/v1/capture-sessions",
        json={
            "shelf_id": ids["shelf_a_assigned"],
            "source_type": "mobile",
            "source_device_id": "supervisor-security-test",
            "capture_mode": "burst",
        },
        headers=headers,
    )

    assert created.status_code == 201, created.text
    created_payload = created.json()
    assert created_payload["store_id"] == store_ids["a"]
    assert created_payload["shelf_id"] == ids["shelf_a_assigned"]
    assert created_payload["created_by_user_id"] == ids["supervisor_a"]
    assert created_payload["source_type"] == "mobile"
    assert created_payload["source_device_id"] == "supervisor-security-test"
    assert created_payload["capture_mode"] == "burst"
    assert created_payload["started_at"] is not None
    assert created_payload["ended_at"] is None

    closed = client.post(
        f"/api/v1/capture-sessions/{created_payload['id']}/close",
        headers=headers,
    )

    assert closed.status_code == 200, closed.text
    closed_payload = closed.json()
    assert closed_payload["id"] == created_payload["id"]
    assert closed_payload["store_id"] == store_ids["a"]
    assert closed_payload["shelf_id"] == ids["shelf_a_assigned"]
    assert closed_payload["created_by_user_id"] == ids["supervisor_a"]
    assert closed_payload["started_at"] == created_payload["started_at"]
    assert closed_payload["ended_at"] is not None

    with main_module.SessionLocal() as db:
        persisted = db.get(models.CaptureSession, created_payload["id"])
        assert persisted is not None
        assert persisted.store_id == store_ids["a"]
        assert persisted.shelf_id == ids["shelf_a_assigned"]
        assert persisted.created_by_user_id == ids["supervisor_a"]
        assert persisted.ended_at is not None


def test_catalogue_is_global_but_shelf_product_assignments_are_store_scoped(auth_client):
    client, ids, _ = auth_client
    supervisor_headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    admin_headers = bearer(ids["admin"], "ADMIN")

    supervisor_products = client.get(
        "/api/v1/products",
        headers=supervisor_headers,
    )
    assert supervisor_products.status_code == 200, supervisor_products.text
    assert [item["id"] for item in supervisor_products.json()] == [ids["product"]]

    supervisor_assignments = client.get(
        "/api/v1/shelf-products",
        headers=supervisor_headers,
    )
    assert supervisor_assignments.status_code == 200, supervisor_assignments.text
    assert len(supervisor_assignments.json()) == 3
    assert {item["shelf_id"] for item in supervisor_assignments.json()} == {
        ids["shelf_a_assigned"],
        ids["shelf_a_unassigned"],
        ids["shelf_a_peer"],
    }

    foreign_assignment = client.get(
        "/api/v1/shelf-products",
        params={"shelf_id": ids["shelf_b"]},
        headers=supervisor_headers,
    )
    assert foreign_assignment.status_code == 200, foreign_assignment.text
    assert foreign_assignment.json() == []

    admin_assignments = client.get(
        "/api/v1/shelf-products",
        headers=admin_headers,
    )
    assert admin_assignments.status_code == 200, admin_assignments.text
    assert len(admin_assignments.json()) == 4
    assert {item["shelf_id"] for item in admin_assignments.json()} == {
        ids["shelf_a_assigned"],
        ids["shelf_a_unassigned"],
        ids["shelf_a_peer"],
        ids["shelf_b"],
    }



def test_admin_can_create_global_warehouse_product_metadata_with_real_jwt(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["admin"], "ADMIN")

    profile_response = client.post(
        "/api/v1/warehouse/product-profiles",
        json={
            "product_id": ids["product"],
            "unit_volume_cm3": 1250,
            "unit_weight_kg": 0.75,
            "temperature_requirement": "CHILLED",
            "is_fragile": True,
            "requires_segregation": False,
        },
        headers=headers,
    )
    assert profile_response.status_code == 201, profile_response.text
    assert profile_response.json()["product_id"] == ids["product"]
    assert profile_response.json()["temperature_requirement"] == "CHILLED"
    assert profile_response.json()["is_fragile"] is True

    packaging_response = client.post(
        "/api/v1/warehouse/product-packaging",
        json={
            "product_id": ids["product"],
            "code": "AUTH-ADMIN-CASE",
            "name": "Caixa criada por ADMIN",
            "package_type": "CASE",
            "base_units_per_package": 6,
            "is_ordering_unit": True,
            "is_replenishment_unit": True,
        },
        headers=headers,
    )
    assert packaging_response.status_code == 201, packaging_response.text
    assert packaging_response.json()["product_id"] == ids["product"]
    assert packaging_response.json()["code"] == "AUTH-ADMIN-CASE"
    assert packaging_response.json()["base_units_per_package"] == 6

    with main_module.SessionLocal() as db:
        persisted_profile = db.query(models.WarehouseProductProfile).filter_by(
            product_id=ids["product"]
        ).one()
        persisted_packaging = db.query(models.ProductPackagingLevel).filter_by(
            product_id=ids["product"],
            code="AUTH-ADMIN-CASE",
        ).one()
        assert persisted_profile.temperature_requirement == "CHILLED"
        assert persisted_profile.is_fragile is True
        assert persisted_packaging.is_ordering_unit is True
        assert persisted_packaging.is_replenishment_unit is True

def test_warehouse_placement_rejects_inactive_location_and_product(auth_client):
    client, ids, store_ids = auth_client
    store_id = store_ids["a"]
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    location_response = client.post(
        "/api/v1/warehouse/locations",
        json={
            "store_id": store_id,
            "code": "A-INACTIVE-PLACEMENT-LOCATION",
            "distance_to_picking_m": 1,
            "max_volume_cm3": 10000,
            "max_weight_kg": 100,
            "temperature_zone": "AMBIENT",
        },
        headers=headers,
    )
    assert location_response.status_code == 201, location_response.text
    location_id = location_response.json()["id"]

    with main_module.SessionLocal() as db:
        location = db.get(models.WarehouseLocation, location_id)
        location.is_active = False
        product = db.get(models.Product, ids["product"])
        product.is_active = False
        db.commit()

    inactive_location = client.post(
        "/api/v1/warehouse/placements",
        json={"location_id": location_id, "product_id": ids["product"], "quantity": 3},
        headers=headers,
    )
    assert inactive_location.status_code == 409
    assert "inactive warehouse location" in inactive_location.json()["detail"]

    with main_module.SessionLocal() as db:
        location = db.get(models.WarehouseLocation, location_id)
        location.is_active = True
        db.commit()

    inactive_product = client.post(
        "/api/v1/warehouse/placements",
        json={"location_id": location_id, "product_id": ids["product"], "quantity": 3},
        headers=headers,
    )
    assert inactive_product.status_code == 409
    assert "inactive product" in inactive_product.json()["detail"]

    with main_module.SessionLocal() as db:
        assert db.query(models.WarehouseProductPlacement).filter_by(
            location_id=location_id, product_id=ids["product"]
        ).count() == 0


def test_physical_warehouse_slotting_api_respects_capacity_and_temperature(auth_client):
    client, ids, store_ids = auth_client
    store_id = store_ids["a"]
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    with main_module.SessionLocal() as db:
        db.add(models.WarehouseProductProfile(
            product_id=ids["product"],
            unit_volume_cm3=100,
            unit_weight_kg=0.5,
            temperature_requirement="AMBIENT",
            is_fragile=False,
            requires_segregation=False,
        ))
        db.commit()

    locations = []
    for code, distance, volume, weight, temperature in [
        ("SLOT-NEAR", 2, 1000, 10, "AMBIENT"),
        ("SLOT-FAR", 8, 600, 5, "AMBIENT"),
        ("SLOT-TOO-SMALL", 1, 400, 10, "AMBIENT"),
        ("SLOT-FROZEN", 3, 1000, 10, "FROZEN"),
    ]:
        response = client.post(
            "/api/v1/warehouse/locations",
            json={
                "store_id": store_id,
                "code": code,
                "distance_to_picking_m": distance,
                "max_volume_cm3": volume,
                "max_weight_kg": weight,
                "temperature_zone": temperature,
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        locations.append(response.json())

    placement = client.post(
        "/api/v1/warehouse/placements",
        json={
            "location_id": locations[0]["id"],
            "product_id": ids["product"],
            "quantity": 2,
        },
        headers=headers,
    )
    assert placement.status_code == 201, placement.text

    with main_module.SessionLocal() as db:
        pallet_level = models.ProductPackagingLevel(
            product_id=ids["product"],
            code="SLOTTING-PALLET",
            name="Palete para teste de slotting",
            package_type="PALLET",
            base_units_per_package=100,
        )
        db.add(pallet_level)
        db.commit()
        db.refresh(pallet_level)
        pallet_level_id = pallet_level.id

    pallet = client.post(
        "/api/v1/warehouse/pallets",
        json={
            "store_id": store_id,
            "product_id": ids["product"],
            "packaging_level_id": pallet_level_id,
            "pallet_code": "SLOTTING-PALLET-01",
            "base_quantity": 20,
            "status": "READY",
            "location_type": "WAREHOUSE",
            "location_code": "SLOT-FAR",
        },
        headers=headers,
    )
    assert pallet.status_code == 201, pallet.text

    response = client.get(
        "/api/v1/warehouse/physical-slotting",
        params={"store_id": store_id, "product_id": ids["product"], "required_quantity": 5},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "CANDIDATES_FOUND"
    assert [item["location_code"] for item in result["candidates"]] == [
        "SLOT-NEAR"
    ]
    assert result["candidates"][0]["required_volume_cm3"] == 500
    assert result["candidates"][0]["required_weight_kg"] == 2.5
    rejected = {item["location_code"]: item["reason"] for item in result["rejected_locations"]}
    assert rejected["SLOT-TOO-SMALL"] == "INSUFFICIENT_VOLUME_CAPACITY"
    assert rejected["SLOT-FROZEN"] == "TEMPERATURE_INCOMPATIBLE"
    assert rejected["SLOT-FAR"] == "UNKNOWN_CURRENT_OCCUPANCY"
    assert "paletes físicas" in result["policy"]
    assert result["automatic_movement_allowed"] is False

    unlocated_pallet = client.post(
        "/api/v1/warehouse/pallets",
        json={
            "store_id": store_id,
            "product_id": ids["product"],
            "packaging_level_id": pallet_level_id,
            "pallet_code": "SLOTTING-PALLET-UNLOCATED",
            "base_quantity": 10,
            "status": "READY",
            "location_type": "WAREHOUSE",
        },
        headers=headers,
    )
    assert unlocated_pallet.status_code == 201, unlocated_pallet.text

    response = client.get(
        "/api/v1/warehouse/physical-slotting",
        params={"store_id": store_id, "product_id": ids["product"], "required_quantity": 5},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["candidates"] == []
    rejected_after_unlocated_pallet = {
        item["location_code"]: item["reason"]
        for item in result["rejected_locations"]
    }
    assert set(rejected_after_unlocated_pallet) == {
        "SLOT-NEAR", "SLOT-FAR", "SLOT-TOO-SMALL", "SLOT-FROZEN"
    }
    assert rejected_after_unlocated_pallet["SLOT-FROZEN"] == "TEMPERATURE_INCOMPATIBLE"
    assert {
        reason
        for location_code, reason in rejected_after_unlocated_pallet.items()
        if location_code != "SLOT-FROZEN"
    } == {"UNKNOWN_CURRENT_OCCUPANCY"}


def test_supervisor_can_create_store_scoped_warehouse_resources_with_real_jwt(auth_client):
    client, ids, store_ids = auth_client
    store_id = store_ids["a"]
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    location_response = client.post(
        "/api/v1/warehouse/locations",
        json={
            "store_id": store_id,
            "code": "A-AUTH-LOCATION",
            "aisle": "A",
            "rack": "01",
            "bin_code": "01",
            "distance_to_picking_m": 8,
            "max_volume_cm3": 50000,
            "max_weight_kg": 250,
            "temperature_zone": "AMBIENT",
        },
        headers=headers,
    )
    assert location_response.status_code == 201, location_response.text
    location_id = location_response.json()["id"]
    assert location_response.json()["store_id"] == store_id

    placement_response = client.post(
        "/api/v1/warehouse/placements",
        json={
            "location_id": location_id,
            "product_id": ids["product"],
            "quantity": 18,
        },
        headers=headers,
    )
    assert placement_response.status_code == 201, placement_response.text
    assert placement_response.json()["location_id"] == location_id
    assert placement_response.json()["product_id"] == ids["product"]
    assert float(placement_response.json()["quantity"]) == 18

    with main_module.SessionLocal() as db:
        pallet_level = models.ProductPackagingLevel(
            product_id=ids["product"],
            code="AUTH-PALLET",
            name="Palete de teste",
            package_type="PALLET",
            base_units_per_package=48,
            is_active=True,
        )
        db.add(pallet_level)
        db.commit()
        db.refresh(pallet_level)
        pallet_level_id = pallet_level.id

    with main_module.SessionLocal() as db:
        snapshots_before = db.query(models.InventorySnapshot).filter_by(
            store_id=store_id, product_id=ids["product"]
        ).count()
        movements_before = db.query(models.InventoryMovement).filter_by(
            store_id=store_id, product_id=ids["product"]
        ).count()

    pallet_response = client.post(
        "/api/v1/warehouse/pallets",
        json={
            "store_id": store_id,
            "product_id": ids["product"],
            "packaging_level_id": pallet_level_id,
            "pallet_code": "A-AUTH-PALLET",
            "lot_code": "LOT-AUTH-01",
            "base_quantity": 48,
            "status": "READY",
            "location_type": "WAREHOUSE",
            "location_code": "A-AUTH-LOCATION",
        },
        headers=headers,
    )
    assert pallet_response.status_code == 201, pallet_response.text
    pallet_id = pallet_response.json()["id"]
    assert pallet_response.json()["store_id"] == store_id
    assert pallet_response.json()["product_id"] == ids["product"]
    assert pallet_response.json()["packaging_level_id"] == pallet_level_id
    assert pallet_response.json()["pallet_code"] == "A-AUTH-PALLET"

    own_locations = client.get(
        "/api/v1/warehouse/locations",
        params={"store_id": store_id},
        headers=headers,
    )
    assert own_locations.status_code == 200
    assert any(item["id"] == location_id for item in own_locations.json())

    own_pallets = client.get(
        "/api/v1/warehouse/pallets",
        params={"store_id": store_id},
        headers=headers,
    )
    assert own_pallets.status_code == 200
    assert any(item["id"] == pallet_id for item in own_pallets.json())

    with main_module.SessionLocal() as db:
        persisted_location = db.get(models.WarehouseLocation, location_id)
        persisted_placement = db.query(models.WarehouseProductPlacement).filter_by(
            location_id=location_id, product_id=ids["product"]
        ).one()
        persisted_pallet = db.get(models.StorePallet, pallet_id)
        events = db.query(models.PalletRotationEvent).filter_by(pallet_id=pallet_id).all()

        assert persisted_location is not None
        assert persisted_location.store_id == store_id
        assert float(persisted_placement.quantity) == 18
        assert persisted_pallet is not None
        assert persisted_pallet.store_id == store_id
        assert len(events) == 1
        assert events[0].event_type == "REGISTERED"
        assert events[0].performed_by_user_id == ids["supervisor_a"]
        assert float(events[0].quantity_before) == 0
        assert float(events[0].quantity_after) == 48

        # Registering a physical pallet is a registry operation, not an
        # inventory receipt: aggregate snapshots and stock movements stay unchanged.
        assert db.query(models.InventorySnapshot).filter_by(
            store_id=store_id, product_id=ids["product"]
        ).count() == snapshots_before
        assert db.query(models.InventoryMovement).filter_by(
            store_id=store_id, product_id=ids["product"]
        ).count() == movements_before



def test_pallet_lifecycle_transitions_are_audited_and_reject_stale_updates(auth_client):
    client, ids, store_ids = auth_client
    store_id = store_ids["a"]
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    with main_module.SessionLocal() as db:
        level = models.ProductPackagingLevel(
            product_id=ids["product"],
            code="LIFECYCLE-PALLET",
            name="Palete para teste de ciclo de vida",
            package_type="PALLET",
            base_units_per_package=48,
            is_active=True,
        )
        warehouse_location = models.WarehouseLocation(
            store_id=store_id,
            code="WH-A",
            distance_to_picking_m=2,
            max_volume_cm3=5000,
            max_weight_kg=100,
            temperature_zone="AMBIENT",
            is_active=True,
        )
        db.add_all([level, warehouse_location])
        db.commit()
        db.refresh(level)
        level_id = level.id

    created = client.post(
        "/api/v1/warehouse/pallets",
        json={
            "store_id": store_id,
            "product_id": ids["product"],
            "packaging_level_id": level_id,
            "pallet_code": "LIFECYCLE-PALLET-01",
            "base_quantity": 48,
            "status": "READY",
            "location_type": "WAREHOUSE",
            "location_code": "WH-A",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    pallet_id = created.json()["id"]

    invalid_transition = client.post(
        f"/api/v1/warehouse/pallets/{pallet_id}/events",
        json={
            "expected_status": "READY",
            "expected_base_quantity": 48,
            "status": "PARTIAL",
            "base_quantity": 24,
            "reason": "Transição não permitida",
        },
        headers=headers,
    )
    assert invalid_transition.status_code == 422

    displayed = client.post(
        f"/api/v1/warehouse/pallets/{pallet_id}/events",
        json={
            "expected_status": "READY",
            "expected_base_quantity": 48,
            "status": "ON_DISPLAY",
            "location_type": "SALES_FLOOR",
            "location_code": "FLOOR-A",
            "reason": "Colocação na área de venda",
        },
        headers=headers,
    )
    assert displayed.status_code == 201, displayed.text
    assert displayed.json()["event_type"] == "STATUS_REVIEWED"
    assert displayed.json()["from_location_type"] == "WAREHOUSE"
    assert displayed.json()["to_location_type"] == "SALES_FLOOR"
    assert float(displayed.json()["quantity_before"]) == 48
    assert float(displayed.json()["quantity_after"]) == 48

    stale_update = client.post(
        f"/api/v1/warehouse/pallets/{pallet_id}/events",
        json={
            "expected_status": "READY",
            "expected_base_quantity": 48,
            "status": "ON_DISPLAY",
            "location_type": "SALES_FLOOR",
            "location_code": "FLOOR-B",
            "reason": "Pedido baseado num estado antigo",
        },
        headers=headers,
    )
    assert stale_update.status_code == 409

    partial = client.post(
        f"/api/v1/warehouse/pallets/{pallet_id}/events",
        json={
            "expected_status": "ON_DISPLAY",
            "expected_base_quantity": 48,
            "status": "PARTIAL",
            "base_quantity": 24,
            "reason": "Venda parcial registada",
        },
        headers=headers,
    )
    assert partial.status_code == 201, partial.text
    assert partial.json()["event_type"] == "STATUS_REVIEWED"
    assert float(partial.json()["quantity_before"]) == 48
    assert float(partial.json()["quantity_after"]) == 24

    events = client.get(
        f"/api/v1/warehouse/pallets/{pallet_id}/events",
        params={"store_id": store_id},
        headers=headers,
    )
    assert events.status_code == 200, events.text
    assert [event["event_type"] for event in events.json()] == [
        "REGISTERED", "STATUS_REVIEWED", "STATUS_REVIEWED"
    ]

    with main_module.SessionLocal() as db:
        persisted = db.get(models.StorePallet, pallet_id)
        assert persisted.status == "PARTIAL"
        assert float(persisted.base_quantity) == 24
        assert persisted.location_type == "SALES_FLOOR"
        assert persisted.location_code == "FLOOR-A"
        assert db.query(models.PalletRotationEvent).filter_by(pallet_id=pallet_id).count() == 3



def test_pallet_registration_and_movement_require_active_store_warehouse_locations(auth_client):
    client, ids, store_ids = auth_client
    store_id = store_ids["a"]
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    with main_module.SessionLocal() as db:
        level = models.ProductPackagingLevel(
            product_id=ids["product"],
            code="PALLET-LOCATION-VALIDATION",
            name="Palete para validação de localização",
            package_type="PALLET",
            base_units_per_package=48,
            is_active=True,
        )
        active_location = models.WarehouseLocation(
            store_id=store_id,
            code="PALLET-BIN-ACTIVE",
            distance_to_picking_m=2,
            max_volume_cm3=5000,
            max_weight_kg=100,
            temperature_zone="AMBIENT",
            is_active=True,
        )
        inactive_location = models.WarehouseLocation(
            store_id=store_id,
            code="PALLET-BIN-INACTIVE",
            distance_to_picking_m=3,
            max_volume_cm3=5000,
            max_weight_kg=100,
            temperature_zone="AMBIENT",
            is_active=False,
        )
        db.add_all([level, active_location, inactive_location])
        db.commit()
        db.refresh(level)
        level_id = level.id

    def register(code, location_code, status="READY", location_type="WAREHOUSE"):
        return client.post(
            "/api/v1/warehouse/pallets",
            json={
                "store_id": store_id,
                "product_id": ids["product"],
                "packaging_level_id": level_id,
                "pallet_code": code,
                "base_quantity": 24,
                "status": status,
                "location_type": location_type,
                "location_code": location_code,
            },
            headers=headers,
        )

    unknown = register("PALLET-UNKNOWN-BIN", "PALLET-BIN-MISSING")
    assert unknown.status_code == 409
    inactive = register("PALLET-INACTIVE-BIN", "PALLET-BIN-INACTIVE")
    assert inactive.status_code == 409
    active = register("PALLET-ACTIVE-BIN", "PALLET-BIN-ACTIVE")
    assert active.status_code == 201, active.text

    display = register(
        "PALLET-MOVE-VALIDATION",
        "FLOOR-VALIDATION",
        status="ON_DISPLAY",
        location_type="SALES_FLOOR",
    )
    assert display.status_code == 201, display.text
    pallet_id = display.json()["id"]

    rejected_move = client.post(
        f"/api/v1/warehouse/pallets/{pallet_id}/events",
        json={
            "expected_status": "ON_DISPLAY",
            "expected_base_quantity": 24,
            "status": "PARTIAL",
            "base_quantity": 12,
            "location_type": "WAREHOUSE",
            "location_code": "PALLET-BIN-INACTIVE",
            "reason": "Tentativa de movimentação para localização inactiva",
        },
        headers=headers,
    )
    assert rejected_move.status_code == 409

    accepted_move = client.post(
        f"/api/v1/warehouse/pallets/{pallet_id}/events",
        json={
            "expected_status": "ON_DISPLAY",
            "expected_base_quantity": 24,
            "status": "PARTIAL",
            "base_quantity": 12,
            "location_type": "WAREHOUSE",
            "location_code": "PALLET-BIN-ACTIVE",
            "reason": "Movimentação para localização activa",
        },
        headers=headers,
    )
    assert accepted_move.status_code == 201, accepted_move.text
    assert accepted_move.json()["to_location_code"] == "PALLET-BIN-ACTIVE"

    with main_module.SessionLocal() as db:
        persisted = db.get(models.StorePallet, pallet_id)
        assert persisted.status == "PARTIAL"
        assert float(persisted.base_quantity) == 12
        assert persisted.location_type == "WAREHOUSE"
        assert persisted.location_code == "PALLET-BIN-ACTIVE"
        assert db.query(models.PalletRotationEvent).filter_by(pallet_id=pallet_id).count() == 2


def test_product_packaging_read_is_global_for_supervisors_and_denied_to_employees(auth_client):
    client, ids, _ = auth_client
    path = "/api/v1/warehouse/product-packaging"
    params = {"product_id": ids["product"]}

    supervisor_response = client.get(
        path,
        params=params,
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert supervisor_response.status_code == 200, supervisor_response.text
    assert [item["id"] for item in supervisor_response.json()] == [ids["active_packaging"]]
    assert supervisor_response.json()[0]["product_id"] == ids["product"]

    admin_response = client.get(
        path,
        params=params,
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert admin_response.status_code == 200, admin_response.text
    assert admin_response.json() == supervisor_response.json()

    employee_response = client.get(
        path,
        params=params,
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert employee_response.status_code == 403


def test_shelf_observation_consensus_is_scoped_to_supervisor_store(auth_client):
    client, ids, store_ids = auth_client

    with main_module.SessionLocal() as db:
        now = datetime.now(timezone.utc)
        observations = []
        for shelf_id, status in (
            (ids["shelf_a_assigned"], "LOW_STOCK"),
            (ids["shelf_b"], "EMPTY"),
        ):
            observations.extend(
                models.Observation(
                    shelf_id=shelf_id,
                    product_id=ids["product"],
                    source="simulation",
                    status=status,
                    confidence=0.95,
                    observed_at=now - timedelta(seconds=seconds_ago),
                )
                for seconds_ago in (60, 40, 20)
            )
        db.add_all(observations)
        db.commit()
        before_count = db.query(models.Observation).count()

    own_response = client.get(
        f"/api/v1/shelves/{ids['shelf_a_assigned']}/observation-consensus",
        params={"product_id": ids["product"]},
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert own_response.status_code == 200, own_response.text
    assert own_response.json()["store_id"] == store_ids["a"]
    assert own_response.json()["shelf_id"] == ids["shelf_a_assigned"]
    assert own_response.json()["product_id"] == ids["product"]
    assert own_response.json()["scope"] == "SHELF_SKU"

    foreign_response = client.get(
        f"/api/v1/shelves/{ids['shelf_b']}/observation-consensus",
        params={"product_id": ids["product"]},
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert foreign_response.status_code == 403

    employee_response = client.get(
        f"/api/v1/shelves/{ids['shelf_a_assigned']}/observation-consensus",
        params={"product_id": ids["product"]},
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert employee_response.status_code == 403

    admin_response = client.get(
        f"/api/v1/shelves/{ids['shelf_b']}/observation-consensus",
        params={"product_id": ids["product"]},
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert admin_response.status_code == 200, admin_response.text
    assert admin_response.json()["store_id"] == store_ids["b"]

    with main_module.SessionLocal() as db:
        assert db.query(models.Observation).count() == before_count

def test_reviewed_training_candidates_are_scoped_to_supervisor_store(auth_client):
    client, ids, store_ids = auth_client

    with main_module.SessionLocal() as db:
        image_a = db.get(models.ShelfImage, ids["image_a"])
        image_b = db.get(models.ShelfImage, ids["image_b"])
        # Keep the candidate eligible and avoid the fixture's pre-existing exemplar.
        image_a.sha256 = "f" * 64
        image_b.retention_status = "ACTIVE"
        db.add_all([
            models.DetectionSkuReview(
                detection_id=ids["detection_a"],
                selected_product_id=ids["product"],
                decision="CONFIRMED",
                reviewer_user_id=ids["admin"],
                notes="Confirmação de teste na loja A",
            ),
            models.DetectionSkuReview(
                detection_id=ids["detection_b"],
                selected_product_id=ids["product"],
                decision="CORRECTED",
                reviewer_user_id=ids["admin"],
                notes="Correção de teste na loja B",
            ),
        ])
        db.commit()

    supervisor_response = client.get(
        "/api/v1/training-candidates/reviewed",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert supervisor_response.status_code == 200, supervisor_response.text
    supervisor_candidates = supervisor_response.json()
    assert len(supervisor_candidates) == 1
    assert supervisor_candidates[0]["shelf_image_id"] == ids["image_a"]
    assert supervisor_candidates[0]["store_id"] == store_ids["a"]

    admin_response = client.get(
        "/api/v1/training-candidates/reviewed",
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert admin_response.status_code == 200, admin_response.text
    admin_candidates = admin_response.json()
    assert {item["shelf_image_id"] for item in admin_candidates} == {
        ids["image_a"], ids["image_b"]
    }
    assert {item["store_id"] for item in admin_candidates} == {
        store_ids["a"], store_ids["b"]
    }

    employee_response = client.get(
        "/api/v1/training-candidates/reviewed",
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert employee_response.status_code == 403

def test_reviewed_sku_evaluation_is_scoped_to_supervisor_store(auth_client, monkeypatch):
    client, ids, store_ids = auth_client
    calls = []

    def fake_report(db, *, store_id=None, model_version=None):
        calls.append({"store_id": store_id, "model_version": model_version})
        return {"store_id": store_id, "model_version": model_version}

    monkeypatch.setattr(main_module, "build_reviewed_prediction_report", fake_report)

    supervisor_headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    own_store_response = client.get(
        "/api/v1/sku-evaluation/reviewed?model_version=vision-v1",
        headers=supervisor_headers,
    )
    assert own_store_response.status_code == 200, own_store_response.text
    assert own_store_response.json() == {
        "store_id": store_ids["a"],
        "model_version": "vision-v1",
    }
    assert calls == [{"store_id": store_ids["a"], "model_version": "vision-v1"}]

    foreign_store_response = client.get(
        f"/api/v1/sku-evaluation/reviewed?store_id={store_ids['b']}",
        headers=supervisor_headers,
    )
    assert foreign_store_response.status_code == 403
    assert len(calls) == 1, "Foreign-store requests must be rejected before report generation"

    admin_response = client.get(
        f"/api/v1/sku-evaluation/reviewed?store_id={store_ids['b']}&model_version=vision-v1",
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert admin_response.status_code == 200, admin_response.text
    assert admin_response.json() == {
        "store_id": store_ids["b"],
        "model_version": "vision-v1",
    }
    assert calls[-1] == {"store_id": store_ids["b"], "model_version": "vision-v1"}

    employee_response = client.get(
        "/api/v1/sku-evaluation/reviewed",
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert employee_response.status_code == 403
    assert len(calls) == 2, "EMPLOYEE requests must be rejected before report generation"

def test_product_embedding_exemplar_listing_is_scoped_to_source_image_store(auth_client):
    client, ids, store_ids = auth_client

    with main_module.SessionLocal() as db:
        image_b = db.get(models.ShelfImage, ids["image_b"])
        image_b.retention_status = "ACTIVE"
        foreign_exemplar = models.ProductEmbeddingExemplar(
            product_id=ids["product"],
            shelf_image_id=image_b.id,
            embedding=[0.75, 0.25, 0.5],
            embedding_dimension=3,
            model_version="auth-embedding-store-b-v1",
            image_sha256=image_b.sha256,
            licence="store-owned-reference-image",
            review_status="PENDING",
            created_by_user_id=ids["employee_b"],
        )
        db.add(foreign_exemplar)
        db.commit()
        db.refresh(foreign_exemplar)
        foreign_exemplar_id = foreign_exemplar.id

    supervisor_response = client.get(
        "/api/v1/product-embedding-exemplars",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert supervisor_response.status_code == 200, supervisor_response.text
    supervisor_exemplars = supervisor_response.json()
    assert {item["id"] for item in supervisor_exemplars} == {
        ids["embedding_exemplar_a"], ids["embedding_exemplar_admin"]
    }
    assert {item["shelf_image_id"] for item in supervisor_exemplars} == {
        ids["image_a"]
    }
    assert all(item.get("shelf_image_id") != ids["image_b"] for item in supervisor_exemplars)

    admin_response = client.get(
        "/api/v1/product-embedding-exemplars",
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert admin_response.status_code == 200, admin_response.text
    admin_exemplars = admin_response.json()
    assert {item["id"] for item in admin_exemplars} == {
        ids["embedding_exemplar_a"], ids["embedding_exemplar_admin"], foreign_exemplar_id
    }
    assert {item["shelf_image_id"] for item in admin_exemplars} == {
        ids["image_a"], ids["image_b"]
    }

    employee_response = client.get(
        "/api/v1/product-embedding-exemplars",
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert employee_response.status_code == 403

def test_embedding_exemplar_review_is_scoped_to_source_store_and_reviewer_role(auth_client):
    client, ids, _ = auth_client

    with main_module.SessionLocal() as db:
        image_a = db.get(models.ShelfImage, ids["image_a"])
        image_b = db.get(models.ShelfImage, ids["image_b"])
        image_b.retention_status = "ACTIVE"

        own_store_exemplar = models.ProductEmbeddingExemplar(
            product_id=ids["product"],
            shelf_image_id=image_a.id,
            embedding=[0.1, 0.2, 0.3],
            embedding_dimension=3,
            model_version="auth-review-own-store-v1",
            image_sha256=image_a.sha256,
            licence="store-owned-reference-image",
            review_status="PENDING",
            created_by_user_id=ids["employee_a"],
        )
        foreign_store_exemplar = models.ProductEmbeddingExemplar(
            product_id=ids["product"],
            shelf_image_id=image_b.id,
            embedding=[0.3, 0.2, 0.1],
            embedding_dimension=3,
            model_version="auth-review-foreign-store-v1",
            image_sha256=image_b.sha256,
            licence="store-owned-reference-image",
            review_status="PENDING",
            created_by_user_id=ids["employee_b"],
        )
        db.add_all([own_store_exemplar, foreign_store_exemplar])
        db.commit()
        db.refresh(own_store_exemplar)
        db.refresh(foreign_store_exemplar)
        own_exemplar_id = own_store_exemplar.id
        foreign_exemplar_id = foreign_store_exemplar.id

    review_payload = {
        "review_status": "APPROVED",
        "review_notes": "Revisão independente autorizada",
    }
    supervisor_headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    own_store_review = client.patch(
        f"/api/v1/product-embedding-exemplars/{own_exemplar_id}/review",
        json=review_payload,
        headers=supervisor_headers,
    )
    assert own_store_review.status_code == 200, own_store_review.text
    assert own_store_review.json()["review_status"] == "APPROVED"

    foreign_store_review = client.patch(
        f"/api/v1/product-embedding-exemplars/{foreign_exemplar_id}/review",
        json=review_payload,
        headers=supervisor_headers,
    )
    assert foreign_store_review.status_code == 403

    employee_review = client.patch(
        f"/api/v1/product-embedding-exemplars/{own_exemplar_id}/review",
        json={"review_status": "REJECTED", "review_notes": "Não autorizado"},
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert employee_review.status_code == 403

    admin_review = client.patch(
        f"/api/v1/product-embedding-exemplars/{foreign_exemplar_id}/review",
        json=review_payload,
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert admin_review.status_code == 200, admin_review.text
    assert admin_review.json()["review_status"] == "APPROVED"

    with main_module.SessionLocal() as db:
        own_persisted = db.get(models.ProductEmbeddingExemplar, own_exemplar_id)
        foreign_persisted = db.get(models.ProductEmbeddingExemplar, foreign_exemplar_id)
        assert own_persisted.review_status == "APPROVED"
        assert own_persisted.reviewed_by_user_id == ids["supervisor_a"]
        assert foreign_persisted.review_status == "APPROVED"
        assert foreign_persisted.reviewed_by_user_id == ids["admin"]


def test_reviewed_sku_evaluation_database_query_isolated_by_supervisor_store(auth_client):
    client, ids, store_ids = auth_client
    reviewed_at = datetime.now(timezone.utc)

    with main_module.SessionLocal() as db:
        image_b = db.get(models.ShelfImage, ids["image_b"])
        image_b.retention_status = "ACTIVE"
        run_a = models.ShelfImageOCRRun(
            shelf_image_id=ids["image_a"],
            provider="sku-evaluation-auth-test",
            model_version="sku-evaluation-ocr-v1",
            status="COMPLETED",
            created_at=reviewed_at - timedelta(minutes=2),
        )
        run_b = models.ShelfImageOCRRun(
            shelf_image_id=ids["image_b"],
            provider="sku-evaluation-auth-test",
            model_version="sku-evaluation-ocr-v1",
            status="COMPLETED",
            created_at=reviewed_at - timedelta(minutes=2),
        )
        db.add_all([run_a, run_b])
        db.flush()

        db.add_all([
            models.DetectionSkuReview(
                detection_id=ids["detection_a"],
                previous_product_id=ids["product"],
                selected_product_id=ids["product"],
                decision="CONFIRMED",
                reviewer_user_id=ids["admin"],
                created_at=reviewed_at,
            ),
            models.DetectionSkuReview(
                detection_id=ids["detection_b"],
                previous_product_id=ids["product"],
                selected_product_id=ids["product"],
                decision="CONFIRMED",
                reviewer_user_id=ids["admin"],
                created_at=reviewed_at,
            ),
            models.ShelfImageFusedEvidence(
                ocr_run_id=run_a.id,
                detection_id=ids["detection_a"],
                status="CONSENSUS",
                suggested_product_id=ids["product"],
                visual_product_id=ids["product"],
                text_product_id=None,
                visual_status="MATCHED",
                text_status="UNKNOWN",
                visual_similarity=0.95,
                text_score=None,
                ocr_confidence=0.9,
                visual_model_version="embed-store-a-v1",
                ocr_provider="sku-evaluation-auth-test",
                ocr_model_version="sku-evaluation-ocr-v1",
                reason="Reviewed prediction in store A",
                created_at=reviewed_at - timedelta(minutes=1),
            ),
            models.ShelfImageFusedEvidence(
                ocr_run_id=run_b.id,
                detection_id=ids["detection_b"],
                status="CONSENSUS",
                suggested_product_id=ids["product"],
                visual_product_id=ids["product"],
                text_product_id=None,
                visual_status="MATCHED",
                text_status="UNKNOWN",
                visual_similarity=0.95,
                text_score=None,
                ocr_confidence=0.9,
                visual_model_version="embed-store-b-v1",
                ocr_provider="sku-evaluation-auth-test",
                ocr_model_version="sku-evaluation-ocr-v1",
                reason="Reviewed prediction in store B",
                created_at=reviewed_at - timedelta(minutes=1),
            ),
        ])
        db.commit()

    supervisor_response = client.get(
        "/api/v1/sku-evaluation/reviewed",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert supervisor_response.status_code == 200, supervisor_response.text
    supervisor_report = supervisor_response.json()
    assert supervisor_report["store_id"] == store_ids["a"]
    assert supervisor_report["sample_count"] == 1
    assert set(supervisor_report["by_model_version"]) == {"embed-store-a-v1"}

    admin_response = client.get(
        "/api/v1/sku-evaluation/reviewed",
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert admin_response.status_code == 200, admin_response.text
    admin_report = admin_response.json()
    assert admin_report["store_id"] is None
    assert admin_report["sample_count"] == 2
    assert set(admin_report["by_model_version"]) == {
        "embed-store-a-v1",
        "embed-store-b-v1",
    }

    employee_response = client.get(
        "/api/v1/sku-evaluation/reviewed",
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert employee_response.status_code == 403


def test_employee_upload_rejects_forged_image_and_unsupported_mime(
    auth_client, monkeypatch, tmp_path
):
    """Reject extension/MIME spoofing before writing files or database rows."""
    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))

    with main_module.SessionLocal() as db:
        before_count = db.query(models.ShelfImage).count()

    forged_png = b"\x89PNG\r\n\x1a\n" + b"not-a-real-png"
    forged_response = client.post(
        "/api/v1/shelf-images",
        data={"shelf_id": str(ids["shelf_a_assigned"])},
        files={"image": ("forged.png", forged_png, "image/png")},
        headers=headers,
    )
    unsupported_response = client.post(
        "/api/v1/shelf-images",
        data={"shelf_id": str(ids["shelf_a_assigned"])},
        files={"image": ("vector.svg", b"<svg></svg>", "image/svg+xml")},
        headers=headers,
    )

    assert forged_response.status_code == 415, forged_response.text
    assert unsupported_response.status_code == 415, unsupported_response.text
    assert not list(tmp_path.rglob("*"))

    with main_module.SessionLocal() as db:
        after_count = db.query(models.ShelfImage).count()
    assert after_count == before_count


def test_employee_upload_sanitizes_client_filename(
    auth_client, monkeypatch, tmp_path
):
    """A client-supplied path must never be persisted as the original filename."""
    from io import BytesIO
    from PIL import Image

    client, ids, store_ids = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))

    image_bytes = BytesIO()
    Image.new("RGB", (8, 8), (55, 95, 135)).save(image_bytes, format="PNG")
    response = client.post(
        "/api/v1/shelf-images",
        data={"shelf_id": str(ids["shelf_a_assigned"])},
        files={
            "image": (
                "../../outside/renamed.png",
                image_bytes.getvalue(),
                "image/png",
            )
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["original_filename"] == "renamed.png"
    # Internal storage paths must not be exposed by the public API schema.
    assert "storage_path" not in payload
    stored_files = list((tmp_path / str(store_ids["a"])).glob("*"))
    assert len(stored_files) == 1
    assert stored_files[0].is_file()



def test_purge_eligibility_preview_is_admin_only_and_non_destructive(auth_client):
    client, ids, _ = auth_client
    admin_headers = bearer(ids["admin"], "ADMIN")
    employee_headers = bearer(ids["employee_a"], "EMPLOYEE")
    image_id = ids["image_b"]

    with main_module.SessionLocal() as db:
        image = db.get(models.ShelfImage, image_id)
        image.purge_not_before = models.utc_now() + timedelta(days=1)
        db.commit()

    denied = client.get(
        f"/api/v1/shelf-images/{image_id}/retention/purge-eligibility",
        headers=employee_headers,
    )
    assert denied.status_code == 403

    preview = client.get(
        f"/api/v1/shelf-images/{image_id}/retention/purge-eligibility",
        headers=admin_headers,
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["eligible"] is False
    assert "retention_period_not_elapsed" in payload["blockers"]
    assert "stored_file_missing_or_unsafe" in payload["blockers"]
    assert payload["deletion_performed"] is False

    with main_module.SessionLocal() as db:
        image = db.get(models.ShelfImage, image_id)
        assert image.retention_status == "RESTRICTED"
        assert image.purged_at is None



def test_admin_can_schedule_cancel_and_audit_future_purge(auth_client):
    client, ids, _ = auth_client
    image_id = ids["image_b"]
    admin_headers = bearer(ids["admin"], "ADMIN")
    employee_headers = bearer(ids["employee_a"], "EMPLOYEE")
    scheduled_at = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    payload = {
        "purge_not_before": scheduled_at,
        "policy_version": "retention-2026-01",
        "reason": "Prazo de retenção aprovado pela política interna",
    }

    denied = client.post(
        f"/api/v1/shelf-images/{image_id}/retention/purge-schedule",
        json=payload,
        headers=employee_headers,
    )
    assert denied.status_code == 403

    scheduled = client.post(
        f"/api/v1/shelf-images/{image_id}/retention/purge-schedule",
        json=payload,
        headers=admin_headers,
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["retention_status"] == "RESTRICTED"
    assert scheduled.json()["retention_policy_version"] == "retention-2026-01"
    assert scheduled.json()["purge_not_before"] is not None

    events = client.get(
        f"/api/v1/shelf-images/{image_id}/retention/events",
        headers=admin_headers,
    )
    assert events.status_code == 200, events.text
    assert any(event["event_type"] == "PURGE_SCHEDULED" for event in events.json())

    cancelled = client.post(
        f"/api/v1/shelf-images/{image_id}/retention/purge-schedule/cancel",
        json={"reason": "Revisão da política de retenção"},
        headers=admin_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["purge_not_before"] is None
    assert cancelled.json()["retention_status"] == "RESTRICTED"

    events = client.get(
        f"/api/v1/shelf-images/{image_id}/retention/events",
        headers=admin_headers,
    )
    assert any(event["event_type"] == "PURGE_CANCELLED" for event in events.json())

    hold = client.post(
        f"/api/v1/shelf-images/{image_id}/retention/legal-hold/apply",
        json={"reason": "Preservação para auditoria legal"},
        headers=admin_headers,
    )
    assert hold.status_code == 200, hold.text
    blocked = client.post(
        f"/api/v1/shelf-images/{image_id}/retention/purge-schedule",
        json=payload,
        headers=admin_headers,
    )
    assert blocked.status_code == 409


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/sales/import-csv",
        "/api/v1/sales/hourly/import-csv",
        "/api/v1/sales/traffic/hourly/import-csv",
    ],
)
def test_sales_csv_upload_endpoints_reject_payloads_over_five_mib(
    auth_client, endpoint
):
    client, ids, store_ids = auth_client
    payload = b"x" * (5 * 1024 * 1024 + 1)

    response = client.post(
        endpoint,
        data={"store_id": str(store_ids["a"]), "source": "IMPORT"},
        files={"file": ("oversized.csv", payload, "text/csv")},
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )

    assert response.status_code == 413, response.text
    assert "5 MB" in response.json()["detail"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/sales/import-csv",
        "/api/v1/sales/hourly/import-csv",
        "/api/v1/sales/traffic/hourly/import-csv",
    ],
)
def test_supervisor_cannot_import_csv_into_another_store(auth_client, endpoint):
    client, ids, store_ids = auth_client
    response = client.post(
        endpoint,
        data={"store_id": str(store_ids["b"]), "source": "IMPORT"},
        files={"file": ("foreign-store.csv", b"untrusted,payload" + bytes([10]), "text/csv")},
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )

    assert response.status_code == 403, response.text


@pytest.mark.parametrize(
    ("endpoint", "csv_header", "row_template"),
    [
        (
            "/api/v1/sales/import-csv",
            "product_id,sales_date,quantity,external_reference",
            "{product_id},2026-11-16,3,CSV-DUPLICATE-DAILY",
        ),
        (
            "/api/v1/sales/hourly/import-csv",
            "product_id,business_date,hour_of_day,quantity,external_reference",
            "{product_id},2026-11-16,10,3,CSV-DUPLICATE-HOURLY",
        ),
        (
            "/api/v1/sales/traffic/hourly/import-csv",
            "business_date,hour_of_day,customer_count,external_reference",
            "2026-11-16,10,12,CSV-DUPLICATE-TRAFFIC",
        ),
    ],
)
def test_sales_csv_import_rejects_existing_external_reference(
    auth_client, endpoint, csv_header, row_template
):
    client, ids, store_ids = auth_client
    payload = (
        csv_header + chr(10)
        + row_template.format(product_id=ids["product"]) + chr(10)
    ).encode("utf-8")
    request_data = {"store_id": str(store_ids["a"]), "source": "IMPORT"}
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")

    first = client.post(
        endpoint,
        data=request_data,
        files={"file": ("sales.csv", payload, "text/csv")},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    duplicate = client.post(
        endpoint,
        data=request_data,
        files={"file": ("sales.csv", payload, "text/csv")},
        headers=headers,
    )
    assert duplicate.status_code == 409, duplicate.text
    assert "no rows were saved" in duplicate.json()["detail"].lower()


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/sales/import-csv",
        "/api/v1/sales/hourly/import-csv",
        "/api/v1/sales/traffic/hourly/import-csv",
    ],
)
def test_sales_csv_import_rejects_non_csv_filename(auth_client, endpoint):
    client, ids, store_ids = auth_client
    response = client.post(
        endpoint,
        data={"store_id": str(store_ids["a"]), "source": "IMPORT"},
        files={"file": ("sales.txt", b"not a csv", "text/plain")},
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert response.status_code == 415, response.text

@pytest.mark.parametrize(
    ("endpoint", "csv_header", "existing_row", "new_row", "model_name"),
    [
        (
            "/api/v1/sales/import-csv",
            "product_id,sales_date,quantity,external_reference",
            "{product_id},2026-11-16,3,ATOMIC-DAILY-EXISTING",
            "{product_id},2026-11-16,4,ATOMIC-DAILY-NEW",
            "DailySalesRecord",
        ),
        (
            "/api/v1/sales/hourly/import-csv",
            "product_id,business_date,hour_of_day,quantity,external_reference",
            "{product_id},2026-11-16,10,3,ATOMIC-HOURLY-EXISTING",
            "{product_id},2026-11-16,11,4,ATOMIC-HOURLY-NEW",
            "HourlySalesRecord",
        ),
        (
            "/api/v1/sales/traffic/hourly/import-csv",
            "business_date,hour_of_day,customer_count,external_reference",
            "2026-11-16,10,12,ATOMIC-TRAFFIC-EXISTING",
            "2026-11-16,11,14,ATOMIC-TRAFFIC-NEW",
            "HourlyStoreTrafficRecord",
        ),
    ],
)
def test_sales_csv_import_rolls_back_all_rows_on_existing_reference_conflict(
    auth_client, endpoint, csv_header, existing_row, new_row, model_name
):
    """A conflict on a later CSV row must not persist earlier new rows."""
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    request_data = {"store_id": str(store_ids["a"]), "source": "IMPORT"}
    existing = existing_row.format(product_id=ids["product"])
    new = new_row.format(product_id=ids["product"])

    seed = client.post(
        endpoint,
        data=request_data,
        files={
            "file": (
                "seed.csv",
                (csv_header + chr(10) + existing + chr(10)).encode("utf-8"),
                "text/csv",
            )
        },
        headers=headers,
    )
    assert seed.status_code == 200, seed.text

    conflicting_payload = (
        csv_header + chr(10) + new + chr(10) + existing + chr(10)
    ).encode("utf-8")
    response = client.post(
        endpoint,
        data=request_data,
        files={"file": ("atomic.csv", conflicting_payload, "text/csv")},
        headers=headers,
    )
    assert response.status_code == 409, response.text
    assert "no rows were saved" in response.json()["detail"].lower()

    record_model = getattr(models, model_name)
    with main_module.SessionLocal() as db:
        assert db.query(record_model).filter(
            record_model.store_id == store_ids["a"],
            record_model.external_reference == new.split(",")[-1],
        ).count() == 0
        assert db.query(record_model).filter(
            record_model.store_id == store_ids["a"],
            record_model.external_reference == existing.split(",")[-1],
        ).count() == 1

@pytest.mark.parametrize(
    ("endpoint", "csv_header", "csv_row"),
    [
        (
            "/api/v1/sales/import-csv",
            "product_id,sales_date,quantity,external_reference",
            "{product_id},2026-11-16,3,STORE-SCOPED-DAILY-REF",
        ),
        (
            "/api/v1/sales/hourly/import-csv",
            "product_id,business_date,hour_of_day,quantity,external_reference",
            "{product_id},2026-11-16,10,3,STORE-SCOPED-HOURLY-REF",
        ),
        (
            "/api/v1/sales/traffic/hourly/import-csv",
            "business_date,hour_of_day,customer_count,external_reference",
            "2026-11-16,10,12,STORE-SCOPED-TRAFFIC-REF",
        ),
    ],
)
def test_csv_external_reference_uniqueness_is_scoped_to_store(
    auth_client, endpoint, csv_header, csv_row
):
    """The same upstream reference may legitimately exist in two different stores."""
    client, ids, store_ids = auth_client
    headers = bearer(ids["admin"], "ADMIN")
    row = csv_row.format(product_id=ids["product"])
    payload = (csv_header + chr(10) + row + chr(10)).encode("utf-8")

    for store_key in ("a", "b"):
        response = client.post(
            endpoint,
            data={"store_id": str(store_ids[store_key]), "source": "IMPORT"},
            files={"file": (f"{store_key}.csv", payload, "text/csv")},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["rows_imported"] == 1

def test_employee_cannot_create_inventory_snapshots_but_supervisor_can(auth_client):
    client, ids, store_ids = auth_client
    payload = {
        "store_id": store_ids["a"],
        "product_id": ids["product"],
        "on_hand_quantity": 24,
        "reserved_quantity": 4,
        "source": "ERP",
        "external_reference": "AUTH-ROLE-SNAPSHOT-001",
    }

    employee_response = client.post(
        "/api/v1/inventory/snapshots",
        json=payload,
        headers=bearer(ids["employee_a"], "ADMIN"),
    )
    assert employee_response.status_code == 403

    supervisor_response = client.post(
        "/api/v1/inventory/snapshots",
        json=payload,
        headers=bearer(ids["supervisor_a"], "EMPLOYEE"),
    )
    assert supervisor_response.status_code == 201, supervisor_response.text
    assert supervisor_response.json()["available_quantity"] == 20


def test_catalogue_and_warehouse_master_data_writes_are_admin_only(auth_client):
    client, ids, _ = auth_client
    protected_paths = (
        "/api/v1/products",
        "/api/v1/shelf-products",
        "/api/v1/warehouse/product-profiles",
        "/api/v1/warehouse/product-packaging",
    )

    for role, user_key in (
        ("SUPERVISOR", "supervisor_a"),
        ("EMPLOYEE", "employee_a"),
    ):
        headers = bearer(ids[user_key], role)
        for path in protected_paths:
            response = client.post(path, json={}, headers=headers)
            assert response.status_code == 403, (
                f"{role} unexpectedly reached {path}: "
                f"{response.status_code} {response.text}"
            )

def test_shelf_product_catalogue_listing_is_scoped_to_supervisor_store(auth_client):
    client, ids, _ = auth_client
    supervisor_headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    admin_headers = bearer(ids["admin"], "ADMIN")

    own_store = client.get("/api/v1/shelf-products", headers=supervisor_headers)
    foreign_shelf = client.get(
        "/api/v1/shelf-products",
        params={"shelf_id": ids["shelf_b"]},
        headers=supervisor_headers,
    )
    all_stores = client.get("/api/v1/shelf-products", headers=admin_headers)

    assert own_store.status_code == 200, own_store.text
    assert own_store.json()
    assert all(row["shelf_id"] != ids["shelf_b"] for row in own_store.json())
    assert foreign_shelf.status_code == 200, foreign_shelf.text
    assert foreign_shelf.json() == []
    assert all_stores.status_code == 200, all_stores.text
    assert {row["shelf_id"] for row in all_stores.json()} >= {
        ids["shelf_a_assigned"], ids["shelf_b"]
    }

def test_admin_cannot_assign_inactive_product_to_shelf(auth_client):
    client, ids, _ = auth_client
    with main_module.SessionLocal() as db:
        inactive_product = models.Product(
            sku="AUTH-INACTIVE-SKU",
            name="Produto desativado",
            is_active=False,
        )
        db.add(inactive_product)
        db.commit()
        inactive_product_id = inactive_product.id

    response = client.post(
        "/api/v1/shelf-products",
        json={
            "shelf_id": ids["shelf_a_unassigned"],
            "product_id": inactive_product_id,
            "target_quantity": 8,
            "min_display_quantity": 2,
        },
        headers=bearer(ids["admin"], "ADMIN"),
    )

    assert response.status_code == 409, response.text
    assert "inactive" in response.json()["detail"].lower()
    with main_module.SessionLocal() as db:
        assert db.query(models.ShelfProduct).filter_by(
            shelf_id=ids["shelf_a_unassigned"],
            product_id=inactive_product_id,
        ).count() == 0


def test_admin_cannot_duplicate_existing_shelf_product_assignment(auth_client):
    client, ids, _ = auth_client
    response = client.post(
        "/api/v1/shelf-products",
        json={
            "shelf_id": ids["shelf_a_assigned"],
            "product_id": ids["product"],
            "target_quantity": 8,
            "min_display_quantity": 2,
        },
        headers=bearer(ids["admin"], "ADMIN"),
    )

    assert response.status_code == 409, response.text
    assert "already assigned" in response.json()["detail"].lower()
    with main_module.SessionLocal() as db:
        assert db.query(models.ShelfProduct).filter_by(
            shelf_id=ids["shelf_a_assigned"],
            product_id=ids["product"],
        ).count() == 1


def test_admin_cannot_create_multiple_active_ordering_or_replenishment_units(auth_client):
    client, ids, _ = auth_client
    headers = bearer(ids["admin"], "ADMIN")
    path = "/api/v1/warehouse/product-packaging"

    first = client.post(
        path,
        json={
            "product_id": ids["product"],
            "code": "AUTH-UNIQUE-UNIT-1",
            "name": "Unidade logística principal",
            "package_type": "CASE",
            "base_units_per_package": 6,
            "is_ordering_unit": True,
            "is_replenishment_unit": True,
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text

    duplicate_ordering = client.post(
        path,
        json={
            "product_id": ids["product"],
            "code": "AUTH-UNIQUE-UNIT-2",
            "name": "Segunda unidade de encomenda",
            "package_type": "CASE",
            "base_units_per_package": 12,
            "is_ordering_unit": True,
            "is_replenishment_unit": False,
        },
        headers=headers,
    )
    assert duplicate_ordering.status_code == 409, duplicate_ordering.text

    duplicate_replenishment = client.post(
        path,
        json={
            "product_id": ids["product"],
            "code": "AUTH-UNIQUE-UNIT-3",
            "name": "Segunda unidade de reposição",
            "package_type": "CASE",
            "base_units_per_package": 24,
            "is_ordering_unit": False,
            "is_replenishment_unit": True,
        },
        headers=headers,
    )
    assert duplicate_replenishment.status_code == 409, duplicate_replenishment.text

    with main_module.SessionLocal() as db:
        active_levels = db.query(models.ProductPackagingLevel).filter_by(
            product_id=ids["product"], is_active=True
        ).all()
        assert sum(level.is_ordering_unit for level in active_levels) == 1
        assert sum(level.is_replenishment_unit for level in active_levels) == 1


def test_supervisor_can_retry_failed_image_once_and_employee_is_denied(auth_client):
    client, ids, _ = auth_client
    image_id = ids["image_a"]

    with main_module.SessionLocal() as db:
        image = db.get(models.ShelfImage, image_id)
        image.analysis_status = "FAILED"
        image.analysis_error = "RuntimeError: previous processing failed"
        image.analysis_started_at = models.utc_now() - timedelta(minutes=5)
        image.analysis_completed_at = models.utc_now()
        image.model_version = "failed-model-v1"
        db.commit()

    supervisor_headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    employee_headers = bearer(ids["employee_a"], "EMPLOYEE")

    retried = client.post(
        f"/api/v1/shelf-images/{image_id}/retry",
        headers=supervisor_headers,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["analysis_status"] == "PENDING"
    assert retried.json()["analysis_error"] is None
    assert retried.json()["analysis_started_at"] is None
    assert retried.json()["analysis_completed_at"] is None
    assert retried.json()["model_version"] is None

    duplicate_retry = client.post(
        f"/api/v1/shelf-images/{image_id}/retry",
        headers=supervisor_headers,
    )
    assert duplicate_retry.status_code == 409, duplicate_retry.text

    employee_retry = client.post(
        f"/api/v1/shelf-images/{image_id}/retry",
        headers=employee_headers,
    )
    assert employee_retry.status_code == 403, employee_retry.text

    with main_module.SessionLocal() as db:
        image = db.get(models.ShelfImage, image_id)
        assert image.analysis_status == "PENDING"
        assert image.analysis_error is None
        assert image.analysis_started_at is None
        assert image.analysis_completed_at is None
        assert image.model_version is None

def test_external_integration_management_is_admin_only_over_http(auth_client):
    client, ids, store_ids = auth_client
    store_id = store_ids["a"]
    headers_by_role = {
        "SUPERVISOR": bearer(ids["supervisor_a"], "SUPERVISOR"),
        "EMPLOYEE": bearer(ids["employee_a"], "EMPLOYEE"),
    }
    requests = [
        ("POST", f"/api/v1/stores/{store_id}/external-integrations", {
            "external_system": "backup-vault",
            "provider": "s3-compatible",
        }),
        ("GET", f"/api/v1/stores/{store_id}/external-integrations", None),
        ("PATCH", f"/api/v1/stores/{store_id}/external-integrations/999999", {
            "status": "REVOKED",
        }),
        ("GET", f"/api/v1/stores/{store_id}/external-integrations/coverage", None),
    ]

    with main_module.SessionLocal() as db:
        before = db.query(models.StoreExternalIntegration).count()

    for role, headers in headers_by_role.items():
        for method, path, payload in requests:
            response = client.request(method, path, json=payload, headers=headers)
            assert response.status_code == 403, (
                f"{role} must not access external integration management: "
                f"{method} {path} returned {response.status_code}"
            )

    with main_module.SessionLocal() as db:
        after = db.query(models.StoreExternalIntegration).count()
    assert after == before, "Denied requests must not create integration records"

def test_store_employee_directory_is_scoped_to_supervisor_store(auth_client):
    client, ids, store_ids = auth_client

    with main_module.SessionLocal() as db:
        inactive_employee = models.User(
            email="inactive-employee-a@example.test",
            full_name="Inactive Employee A",
            password_hash="test-only",
            role="EMPLOYEE",
            store_id=store_ids["a"],
            is_active=False,
        )
        db.add(inactive_employee)
        db.commit()

    supervisor_response = client.get(
        "/api/v1/store-employees",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert supervisor_response.status_code == 200, supervisor_response.text
    supervisor_employees = supervisor_response.json()
    assert {item["id"] for item in supervisor_employees} == {
        ids["employee_a"], ids["employee_a_peer"]
    }
    assert all(item["store_id"] == store_ids["a"] for item in supervisor_employees)
    assert all(item["is_active"] for item in supervisor_employees)

    foreign_store_response = client.get(
        f"/api/v1/store-employees?store_id={store_ids['b']}",
        headers=bearer(ids["supervisor_a"], "SUPERVISOR"),
    )
    assert foreign_store_response.status_code == 403

    admin_response = client.get(
        f"/api/v1/store-employees?store_id={store_ids['b']}",
        headers=bearer(ids["admin"], "ADMIN"),
    )
    assert admin_response.status_code == 200, admin_response.text
    assert {item["id"] for item in admin_response.json()} == {ids["employee_b"]}

    employee_response = client.get(
        "/api/v1/store-employees",
        headers=bearer(ids["employee_a"], "EMPLOYEE"),
    )
    assert employee_response.status_code == 403



def test_shelf_image_external_artifact_governance_is_admin_only_over_http(auth_client):
    client, ids, store_ids = auth_client
    image_id = ids["image_a"]
    with main_module.SessionLocal() as db:
        artifact = models.ShelfImageArtifactReference(
            shelf_image_id=image_id,
            store_id=store_ids["a"],
            artifact_type="OTHER",
            external_system="authorization-test",
            external_reference="object://authorization-test/artifact-1",
            declared_by_user_id=ids["admin"],
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        artifact_id = artifact.id

    headers_by_role = {
        "SUPERVISOR": bearer(ids["supervisor_a"], "SUPERVISOR"),
        "EMPLOYEE": bearer(ids["employee_a"], "EMPLOYEE"),
    }
    snapshot_payload = {
        "external_system": "authorization-test",
        "snapshot_id": "denied-snapshot",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inventory_complete": True,
        "entries": [{
            "artifact_type": "OTHER",
            "external_reference": "object://authorization-test/artifact-1",
            "state": "PRESENT",
        }],
        "key_id": "legacy",
        "signature": "a" * 64,
    }
    requests = [
        ("POST", f"/api/v1/shelf-images/{image_id}/artifacts", {
            "artifact_type": "OTHER",
            "external_system": "authorization-test",
            "external_reference": "object://authorization-test/unauthorized-create",
        }),
        ("GET", f"/api/v1/shelf-images/{image_id}/artifacts", None),
        ("POST", f"/api/v1/shelf-images/{image_id}/artifact-inventory-snapshots", snapshot_payload),
        ("GET", f"/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/access", None),
        ("POST", f"/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/disposition-events", {
            "action": "PROPOSE",
            "reason": "Pedido de teste não autorizado",
        }),
        ("GET", f"/api/v1/shelf-images/{image_id}/artifacts/{artifact_id}/disposition-events", None),
    ]

    with main_module.SessionLocal() as db:
        before = {
            "artifacts": db.query(models.ShelfImageArtifactReference).count(),
            "snapshots": db.query(models.ShelfImageArtifactInventorySnapshot).count(),
            "disposition_events": db.query(models.ShelfImageArtifactDispositionEvent).count(),
        }

    for role, headers in headers_by_role.items():
        for method, path, payload in requests:
            response = client.request(method, path, json=payload, headers=headers)
            assert response.status_code == 403, (
                f"{role} must not access external artifact governance: "
                f"{method} {path} returned {response.status_code}"
            )

    with main_module.SessionLocal() as db:
        after = {
            "artifacts": db.query(models.ShelfImageArtifactReference).count(),
            "snapshots": db.query(models.ShelfImageArtifactInventorySnapshot).count(),
            "disposition_events": db.query(models.ShelfImageArtifactDispositionEvent).count(),
        }
    assert after == before, "Denied requests must not persist artifact governance records"



def test_store_external_integration_governance_is_admin_only_over_http(auth_client):
    client, ids, store_ids = auth_client
    store_id = store_ids["a"]
    with main_module.SessionLocal() as db:
        integration = models.StoreExternalIntegration(
            store_id=store_id,
            external_system="AUTH-EXTERNAL-BASELINE",
            provider="test-provider",
            status="ACTIVE",
            required_for_retention=True,
            capabilities=["inventory.read"],
            created_by_user_id=ids["admin"],
            updated_by_user_id=ids["admin"],
        )
        db.add(integration)
        db.commit()
        db.refresh(integration)
        integration_id = integration.id

    headers_by_role = {
        "SUPERVISOR": bearer(ids["supervisor_a"], "SUPERVISOR"),
        "EMPLOYEE": bearer(ids["employee_a"], "EMPLOYEE"),
    }
    requests = [
        ("POST", f"/api/v1/stores/{store_id}/external-integrations", {
            "external_system": "AUTH-EXTERNAL-UNAUTHORIZED",
            "provider": "test-provider",
            "required_for_retention": True,
            "capabilities": ["inventory.read"],
        }),
        ("GET", f"/api/v1/stores/{store_id}/external-integrations", None),
        ("GET", f"/api/v1/stores/{store_id}/external-integrations/coverage", None),
        ("PATCH", f"/api/v1/stores/{store_id}/external-integrations/{integration_id}", {
            "status": "REVOKED",
        }),
    ]

    with main_module.SessionLocal() as db:
        before_count = db.query(models.StoreExternalIntegration).count()
        before = db.get(models.StoreExternalIntegration, integration_id)
        before_state = (before.status, before.required_for_retention, list(before.capabilities))

    for role, headers in headers_by_role.items():
        for method, path, payload in requests:
            response = client.request(method, path, json=payload, headers=headers)
            assert response.status_code == 403, (
                f"{role} must not access external integration governance: "
                f"{method} {path} returned {response.status_code}"
            )

    with main_module.SessionLocal() as db:
        after_count = db.query(models.StoreExternalIntegration).count()
        after = db.get(models.StoreExternalIntegration, integration_id)
        after_state = (after.status, after.required_for_retention, list(after.capabilities))

    assert after_count == before_count, "Denied requests must not create external integrations"
    assert after_state == before_state, "Denied requests must not mutate external integration policy"


def test_admin_external_integration_management_is_store_scoped_over_http(auth_client):
    client, ids, store_ids = auth_client
    admin_headers = bearer(ids["admin"], "ADMIN")
    external_system = "auth-backup-store-a"

    created = client.post(
        f"/api/v1/stores/{store_ids['a']}/external-integrations",
        json={
            "external_system": external_system,
            "provider": "test-provider",
            "required_for_retention": True,
            "capabilities": ["inventory.read", "retention.attest"],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    integration = created.json()
    integration_id = integration["id"]
    assert integration["store_id"] == store_ids["a"]
    assert integration["external_system"] == external_system
    assert integration["status"] == "ACTIVE"
    assert integration["required_for_retention"] is True
    assert integration["created_by_user_id"] == ids["admin"]
    assert not ({"secret", "secret_key", "signing_key", "credentials"} & set(integration))

    store_a_list = client.get(
        f"/api/v1/stores/{store_ids['a']}/external-integrations",
        headers=admin_headers,
    )
    store_b_list = client.get(
        f"/api/v1/stores/{store_ids['b']}/external-integrations",
        headers=admin_headers,
    )
    assert store_a_list.status_code == 200, store_a_list.text
    assert [item["id"] for item in store_a_list.json()] == [integration_id]
    assert store_b_list.status_code == 200, store_b_list.text
    assert store_b_list.json() == []

    coverage = client.get(
        f"/api/v1/stores/{store_ids['a']}/external-integrations/coverage",
        headers=admin_headers,
    )
    assert coverage.status_code == 200, coverage.text
    assert coverage.json()["store_id"] == store_ids["a"]
    assert coverage.json()["required_integrations"] == 1
    assert coverage.json()["active_required_integrations"] == 1
    assert coverage.json()["never_seen_integrations"] == [external_system]

    cross_store_update = client.patch(
        f"/api/v1/stores/{store_ids['b']}/external-integrations/{integration_id}",
        json={"status": "REVOKED"},
        headers=admin_headers,
    )
    assert cross_store_update.status_code == 404, cross_store_update.text

    unchanged = client.get(
        f"/api/v1/stores/{store_ids['a']}/external-integrations",
        headers=admin_headers,
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()[0]["status"] == "ACTIVE"

    revoked = client.patch(
        f"/api/v1/stores/{store_ids['a']}/external-integrations/{integration_id}",
        json={"status": "REVOKED", "required_for_retention": False},
        headers=admin_headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "REVOKED"
    assert revoked.json()["required_for_retention"] is False
    assert revoked.json()["updated_by_user_id"] == ids["admin"]




def test_admin_can_manage_store_external_integrations_over_http(auth_client):
    client, ids, store_ids = auth_client
    store_id = store_ids["a"]
    headers = bearer(ids["admin"], "ADMIN")
    external_system = "AUTH-HTTP-ADMIN-SOURCE"

    created = client.post(
        f"/api/v1/stores/{store_id}/external-integrations",
        json={
            "external_system": external_system,
            "provider": "test-provider",
            "required_for_retention": True,
            "capabilities": ["inventory.read", "inventory.attest"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    created_payload = created.json()
    assert created_payload["store_id"] == store_id
    assert created_payload["external_system"] == external_system
    assert created_payload["status"] == "ACTIVE"
    assert created_payload["required_for_retention"] is True
    assert created_payload["last_seen_at"] is None
    assert "secret" not in created_payload
    integration_id = created_payload["id"]

    listed = client.get(
        f"/api/v1/stores/{store_id}/external-integrations",
        headers=headers,
    )
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == integration_id for item in listed.json())

    coverage = client.get(
        f"/api/v1/stores/{store_id}/external-integrations/coverage",
        headers=headers,
    )
    assert coverage.status_code == 200, coverage.text
    assert coverage.json()["required_integrations"] == 1
    assert coverage.json()["active_required_integrations"] == 1
    assert coverage.json()["never_seen_integrations"] == [external_system]
    assert coverage.json()["coverage_complete"] is False

    updated = client.patch(
        f"/api/v1/stores/{store_id}/external-integrations/{integration_id}",
        json={"status": "REVOKED"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "REVOKED"

    revoked_coverage = client.get(
        f"/api/v1/stores/{store_id}/external-integrations/coverage",
        headers=headers,
    )
    assert revoked_coverage.status_code == 200, revoked_coverage.text
    assert revoked_coverage.json()["active_required_integrations"] == 0
    assert revoked_coverage.json()["missing_or_revoked_integrations"] == [external_system]


def test_employee_cannot_access_human_review_workflows_over_http(auth_client):
    """Employees may inspect their own detection history, but cannot perform reviews."""
    client, ids, _ = auth_client
    headers = bearer(ids["employee_a"], "EMPLOYEE")
    detection_id = ids["detection_a"]
    review_path = f"/api/v1/shelf-image-detections/{detection_id}/reviews"

    with main_module.SessionLocal() as db:
        before = db.query(models.DetectionSkuReview).count()

    requests = [
        ("GET", "/api/v1/shelf-image-review-queue"),
        ("GET", "/api/v1/shelf-image-review-queue/summary"),
        ("GET", "/api/v1/sku-evaluation/reviewed"),
        ("GET", "/api/v1/training-candidates/reviewed"),
        ("POST", review_path),
    ]
    for method, path in requests:
        response = client.request(method, path, json={} if method == "POST" else None, headers=headers)
        assert response.status_code == 403, (
            f"EMPLOYEE must not access human-review workflow: "
            f"{method} {path} returned {response.status_code}"
        )

    with main_module.SessionLocal() as db:
        after = db.query(models.DetectionSkuReview).count()
    assert after == before, "Denied employee review requests must not create review records"


def test_supervisor_cannot_access_other_store_warehouse_resources_over_http(auth_client):
    """Warehouse location and placement endpoints must enforce store ownership."""
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    store_b = store_ids["b"]
    location_b = ids["warehouse_location_b"]

    with main_module.SessionLocal() as db:
        locations_before = db.query(models.WarehouseLocation).filter_by(store_id=store_b).count()
        placements_before = db.query(models.WarehouseProductPlacement).count()

    requests = [
        ("GET", f"/api/v1/warehouse/locations?store_id={store_b}", None),
        ("POST", "/api/v1/warehouse/locations", {
            "store_id": store_b,
            "code": "A-CROSS-STORE-ATTEMPT",
            "distance_to_picking_m": 5,
            "max_volume_cm3": 50000,
            "max_weight_kg": 50,
        }),
        ("POST", "/api/v1/warehouse/placements", {
            "location_id": location_b,
            "product_id": ids["product"],
            "quantity": 3,
        }),
    ]
    for method, path, payload in requests:
        response = client.request(method, path, json=payload, headers=headers)
        assert response.status_code == 403, (
            f"SUPERVISOR from store A must not access store B warehouse data: "
            f"{method} {path} returned {response.status_code}"
        )

    with main_module.SessionLocal() as db:
        locations_after = db.query(models.WarehouseLocation).filter_by(store_id=store_b).count()
        placements_after = db.query(models.WarehouseProductPlacement).count()
    assert locations_after == locations_before, "Denied cross-store location creation must have no side effects"
    assert placements_after == placements_before, "Denied cross-store placement creation must have no side effects"


def test_supervisor_cannot_access_other_store_pallets_policies_or_events_over_http(auth_client):
    """A supervisor cannot read or mutate pallet operations belonging to another store."""
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    store_b = store_ids["b"]

    with main_module.SessionLocal() as db:
        pallet_level = models.ProductPackagingLevel(
            product_id=ids["product"],
            code="AUTH-PALLET-LEVEL",
            name="Palete de teste",
            package_type="PALLET",
            base_units_per_package=100,
            is_active=True,
        )
        db.add(pallet_level)
        db.flush()
        pallet = models.StorePallet(
            store_id=store_b,
            product_id=ids["product"],
            packaging_level_id=pallet_level.id,
            pallet_code="AUTH-B-PALLET-01",
            base_quantity=10,
            status="READY",
            location_type="WAREHOUSE",
            location_code="B-WAREHOUSE-01",
        )
        policy = models.PalletRotationPolicy(
            store_id=store_b,
            product_id=ids["product"],
            threshold_ratio=0.5,
            is_enabled=True,
        )
        db.add_all([pallet, policy])
        db.flush()
        db.add(models.PalletRotationEvent(
            pallet_id=pallet.id,
            event_type="REGISTERED",
            to_location_type="WAREHOUSE",
            to_location_code="B-WAREHOUSE-01",
            quantity_before=0,
            quantity_after=10,
            reason="Initial test fixture",
        ))
        db.commit()
        pallet_id = pallet.id
        policy_id = policy.id
        packaging_level_id = pallet_level.id

    with main_module.SessionLocal() as db:
        events_before = db.query(models.PalletRotationEvent).filter_by(pallet_id=pallet_id).count()
        policy_before = db.get(models.PalletRotationPolicy, policy_id)
        policy_state_before = (float(policy_before.threshold_ratio), policy_before.is_enabled)
        pallet_before = db.get(models.StorePallet, pallet_id)
        pallet_state_before = (pallet_before.status, float(pallet_before.base_quantity), pallet_before.location_type)

    requests = [
        ("GET", f"/api/v1/warehouse/pallets?store_id={store_b}", None),
        ("POST", "/api/v1/warehouse/pallets", {
            "store_id": store_b,
            "product_id": ids["product"],
            "packaging_level_id": packaging_level_id,
            "pallet_code": "AUTH-CROSS-STORE-ATTEMPT",
            "base_quantity": 10,
            "status": "READY",
            "location_type": "WAREHOUSE",
            "location_code": "B-WAREHOUSE-01",
        }),
        ("PATCH", f"/api/v1/warehouse/pallet-rotation/policies/{policy_id}", {
            "threshold_ratio": 0.75,
        }),
        ("GET", f"/api/v1/warehouse/pallets/{pallet_id}/events?store_id={store_b}", None),
        ("POST", f"/api/v1/warehouse/pallets/{pallet_id}/events", {
            "expected_status": "READY",
            "expected_base_quantity": 10,
            "status": "QUARANTINED",
            "reason": "Cross-store authorization probe",
        }),
    ]
    for method, path, payload in requests:
        response = client.request(method, path, json=payload, headers=headers)
        assert response.status_code == 403, (
            f"SUPERVISOR from store A must not access store B pallet operations: "
            f"{method} {path} returned {response.status_code}"
        )

    with main_module.SessionLocal() as db:
        events_after = db.query(models.PalletRotationEvent).filter_by(pallet_id=pallet_id).count()
        policy_after = db.get(models.PalletRotationPolicy, policy_id)
        policy_state_after = (float(policy_after.threshold_ratio), policy_after.is_enabled)
        pallet_after = db.get(models.StorePallet, pallet_id)
        pallet_state_after = (pallet_after.status, float(pallet_after.base_quantity), pallet_after.location_type)
    assert events_after == events_before, "Denied cross-store event requests must not append lifecycle events"
    assert policy_state_after == policy_state_before, "Denied cross-store requests must not alter rotation policy"
    assert pallet_state_after == pallet_state_before, "Denied cross-store requests must not alter pallet state"

def test_supervisor_cannot_access_other_store_sales_and_forecasts_over_http(auth_client):
    """Sales and forecast endpoints must reject a supervisor from another store."""
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    store_b = store_ids["b"]
    product_id = ids["product"]
    hourly = {
        "store_id": store_b, "product_id": product_id, "business_date": "2026-11-18",
        "hour_of_day": 10, "quantity": 4, "source": "POS",
        "external_reference": "AUTH-CROSS-STORE-HOURLY",
    }
    traffic = {
        "store_id": store_b, "business_date": "2026-11-18", "hour_of_day": 10,
        "customer_count": 12, "source": "POS", "external_reference": "AUTH-CROSS-STORE-TRAFFIC",
    }
    with main_module.SessionLocal() as db:
        daily_before = db.query(models.DailySalesRecord).filter_by(store_id=store_b).count()
        hourly_before = db.query(models.HourlySalesRecord).filter_by(store_id=store_b).count()
        traffic_before = db.query(models.HourlyStoreTrafficRecord).filter_by(store_id=store_b).count()

    attempts = [
        ("POST", "/api/v1/sales/daily", {
            "store_id": store_b, "product_id": product_id, "sales_date": "2026-11-18",
            "quantity": 4, "source": "POS", "external_reference": "AUTH-CROSS-STORE-DAILY",
        }),
        ("POST", "/api/v1/sales/hourly", hourly),
        ("POST", "/api/v1/sales/traffic/hourly", traffic),
        ("POST", "/api/v1/sales/hourly/batch", {"records": [hourly]}),
        ("POST", "/api/v1/sales/traffic/hourly/batch", {"records": [traffic]}),
        ("GET", f"/api/v1/sales/daily?store_id={store_b}&product_id={product_id}&source=POS&days=7", None),
        ("GET", f"/api/v1/sales/hourly?store_id={store_b}", None),
        ("GET", f"/api/v1/sales/traffic/hourly?store_id={store_b}", None),
        ("GET", f"/api/v1/forecasting/traffic-peaks?store_id={store_b}&days=14", None),
        ("GET", f"/api/v1/forecasting/hourly-demand?store_id={store_b}&product_id={product_id}&horizon_days=7&history_days=28&source=POS", None),
        ("GET", f"/api/v1/forecasting/demand?store_id={store_b}&product_id={product_id}&source=POS&lead_time_days=2&days=7", None),
        ("GET", f"/api/v1/forecasting/stockout-risk?store_id={store_b}&product_id={product_id}&source=POS&lead_time_days=2&days=7", None),
        ("GET", f"/api/v1/forecasting/stockout-risk/portfolio?store_id={store_b}&source=POS&lead_time_days=2&days=7", None),
        ("GET", f"/api/v1/warehouse/slotting-recommendations?store_id={store_b}&source=POS&days=7", None),
        ("GET", f"/api/v1/warehouse/pallet-rotation/hourly-profile?store_id={store_b}&product_id={product_id}&days=7", None),
        ("GET", f"/api/v1/warehouse/pallet-rotation/portfolio-from-history?store_id={store_b}&current_hour=10&days=7", None),
    ]
    for method, path, payload in attempts:
        response = client.request(method, path, json=payload, headers=headers)
        assert response.status_code == 403, f"{method} {path} returned {response.status_code}"

    with main_module.SessionLocal() as db:
        assert db.query(models.DailySalesRecord).filter_by(store_id=store_b).count() == daily_before
        assert db.query(models.HourlySalesRecord).filter_by(store_id=store_b).count() == hourly_before
        assert db.query(models.HourlyStoreTrafficRecord).filter_by(store_id=store_b).count() == traffic_before


def test_supervisor_cannot_import_other_store_hourly_sales_or_traffic_csv_over_http(auth_client):
    """CSV ingestion must enforce store scope before parsing or persisting rows."""
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    store_b = store_ids["b"]

    sales_csv = (
        "product_id,business_date,hour_of_day,quantity,external_reference\n"
        "not-a-product,2026-11-18,10,4,CROSS-STORE-SALES-CSV\n"
    ).encode("utf-8")
    traffic_csv = (
        "business_date,hour_of_day,customer_count,external_reference\n"
        "2026-11-18,10,12,CROSS-STORE-TRAFFIC-CSV\n"
    ).encode("utf-8")

    daily_csv = (
        "product_id,sales_date,quantity,external_reference\n"
        "not-a-product,2026-11-18,4,CROSS-STORE-DAILY-CSV\n"
    ).encode("utf-8")

    with main_module.SessionLocal() as db:
        daily_before = db.query(models.DailySalesRecord).filter_by(store_id=store_b).count()
        sales_before = db.query(models.HourlySalesRecord).filter_by(store_id=store_b).count()
        traffic_before = db.query(models.HourlyStoreTrafficRecord).filter_by(store_id=store_b).count()

    attempts = [
        ("/api/v1/sales/import-csv", daily_csv, "daily-sales.csv"),
        ("/api/v1/sales/hourly/import-csv", sales_csv, "sales.csv"),
        ("/api/v1/sales/traffic/hourly/import-csv", traffic_csv, "traffic.csv"),
    ]
    for path, payload, filename in attempts:
        response = client.post(
            path,
            data={"store_id": str(store_b), "source": "IMPORT"},
            files={"file": (filename, payload, "text/csv")},
            headers=headers,
        )
        assert response.status_code == 403, f"POST {path} returned {response.status_code}: {response.text}"

    with main_module.SessionLocal() as db:
        daily_after = db.query(models.DailySalesRecord).filter_by(store_id=store_b).count()
        sales_after = db.query(models.HourlySalesRecord).filter_by(store_id=store_b).count()
        traffic_after = db.query(models.HourlyStoreTrafficRecord).filter_by(store_id=store_b).count()
    assert daily_after == daily_before, "Denied daily sales CSV import must not persist sales"
    assert sales_after == sales_before, "Denied hourly sales CSV import must not persist sales"
    assert traffic_after == traffic_before, "Denied traffic CSV import must not persist traffic"



def test_zone_and_shelf_routes_enforce_admin_writes_and_store_scoped_reads(auth_client):
    """Store layout reads are tenant-scoped and only ADMIN can change the hierarchy."""
    client, ids, store_ids = auth_client
    supervisor_headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    employee_headers = bearer(ids["employee_a"], "EMPLOYEE")
    admin_headers = bearer(ids["admin"], "ADMIN")

    with main_module.SessionLocal() as db:
        zone_b = db.query(models.Zone).filter_by(store_id=store_ids["b"]).one()
        zones_before = db.query(models.Zone).count()
        shelves_before = db.query(models.Shelf).count()
        zone_b_id = zone_b.id

    supervisor_zones = client.get("/api/v1/zones", headers=supervisor_headers)
    supervisor_foreign_zones = client.get(
        "/api/v1/zones", params={"store_id": store_ids["b"]}, headers=supervisor_headers
    )
    supervisor_shelves = client.get("/api/v1/shelves", headers=supervisor_headers)
    assert supervisor_zones.status_code == 200, supervisor_zones.text
    assert {zone["store_id"] for zone in supervisor_zones.json()} == {store_ids["a"]}
    assert supervisor_foreign_zones.status_code == 403
    assert supervisor_shelves.status_code == 200, supervisor_shelves.text
    assert {shelf["id"] for shelf in supervisor_shelves.json()} == {
        ids["shelf_a_assigned"], ids["shelf_a_unassigned"], ids["shelf_a_peer"]
    }

    denied_zone = client.post(
        "/api/v1/zones", json={"store_id": store_ids["b"], "name": "Unauthorized zone"},
        headers=supervisor_headers,
    )
    denied_shelf = client.post(
        "/api/v1/shelves", json={"zone_id": zone_b_id, "code": "UNAUTHORIZED-SHELF"},
        headers=supervisor_headers,
    )
    employee_zones = client.get("/api/v1/zones", headers=employee_headers)
    employee_shelves = client.get("/api/v1/shelves", headers=employee_headers)
    assert denied_zone.status_code == 403
    assert denied_shelf.status_code == 403
    assert employee_zones.status_code == 403
    assert employee_shelves.status_code == 403

    with main_module.SessionLocal() as db:
        assert db.query(models.Zone).count() == zones_before
        assert db.query(models.Shelf).count() == shelves_before

    admin_zone = client.post(
        "/api/v1/zones", json={"store_id": store_ids["b"], "name": "Admin-created zone"},
        headers=admin_headers,
    )
    assert admin_zone.status_code == 201, admin_zone.text
    admin_shelf = client.post(
        "/api/v1/shelves", json={"zone_id": admin_zone.json()["id"], "code": "ADMIN-CREATED-SHELF"},
        headers=admin_headers,
    )
    assert admin_shelf.status_code == 201, admin_shelf.text
    admin_zones = client.get("/api/v1/zones", headers=admin_headers)
    assert admin_zones.status_code == 200
    assert {zone["store_id"] for zone in admin_zones.json()} == {store_ids["a"], store_ids["b"]}


def test_sales_batches_reject_mixed_store_payloads_over_http(auth_client):
    """A batch must not mix tenant IDs, even when its first row is in scope."""
    client, ids, store_ids = auth_client
    headers = bearer(ids["supervisor_a"], "SUPERVISOR")
    store_a, store_b = store_ids["a"], store_ids["b"]
    product_id = ids["product"]

    sales_rows = [
        {
            "store_id": store_a, "product_id": product_id, "business_date": "2026-11-18",
            "hour_of_day": 11, "quantity": 2, "source": "POS",
            "external_reference": "AUTH-MIXED-SALES-A",
        },
        {
            "store_id": store_b, "product_id": product_id, "business_date": "2026-11-18",
            "hour_of_day": 12, "quantity": 3, "source": "POS",
            "external_reference": "AUTH-MIXED-SALES-B",
        },
    ]
    traffic_rows = [
        {
            "store_id": store_a, "business_date": "2026-11-18", "hour_of_day": 11,
            "customer_count": 8, "source": "POS", "external_reference": "AUTH-MIXED-TRAFFIC-A",
        },
        {
            "store_id": store_b, "business_date": "2026-11-18", "hour_of_day": 12,
            "customer_count": 9, "source": "POS", "external_reference": "AUTH-MIXED-TRAFFIC-B",
        },
    ]

    with main_module.SessionLocal() as db:
        sales_before = {
            store_id: db.query(models.HourlySalesRecord).filter_by(store_id=store_id).count()
            for store_id in (store_a, store_b)
        }
        traffic_before = {
            store_id: db.query(models.HourlyStoreTrafficRecord).filter_by(store_id=store_id).count()
            for store_id in (store_a, store_b)
        }

    sales_response = client.post(
        "/api/v1/sales/hourly/batch", json={"records": sales_rows}, headers=headers
    )
    traffic_response = client.post(
        "/api/v1/sales/traffic/hourly/batch", json={"records": traffic_rows}, headers=headers
    )
    assert sales_response.status_code == 422, sales_response.text
    assert traffic_response.status_code == 422, traffic_response.text

    with main_module.SessionLocal() as db:
        for store_id in (store_a, store_b):
            assert db.query(models.HourlySalesRecord).filter_by(store_id=store_id).count() == sales_before[store_id]
            assert db.query(models.HourlyStoreTrafficRecord).filter_by(store_id=store_id).count() == traffic_before[store_id]
