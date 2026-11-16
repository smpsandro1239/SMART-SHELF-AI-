import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import models  # noqa: F401
from app import main as main_module
from app.main import app

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_database():
    previous_override = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    Base.metadata.drop_all(bind=TEST_ENGINE)


def create_store_and_product(client):
    store = client.post("/api/v1/stores", json={"code": "INV-01", "name": "Loja inventário"})
    product = client.post("/api/v1/products", json={"sku": "INV-SKU-01", "name": "Arroz 1 kg"})
    return store.json()["id"], product.json()["id"]


def test_inventory_snapshot_records_available_quantity_and_history():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        first = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 25, "reserved_quantity": 5,
            "source": "ERP", "external_reference": "ERP-0001",
        })
        assert first.status_code == 201
        assert first.json()["available_quantity"] == 20

        second = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 18, "reserved_quantity": 3,
            "source": "WMS", "external_reference": "WMS-0002",
        })
        assert second.status_code == 201
        history = client.get("/api/v1/inventory/snapshots", params={
            "store_id": store_id, "product_id": product_id,
        })
        assert history.status_code == 200
        assert len(history.json()) == 2

        latest = client.get("/api/v1/inventory/latest", params={
            "store_id": store_id, "product_id": product_id,
        })
        assert latest.status_code == 200
        assert latest.json()["available_quantity"] == 15


def test_inventory_rejects_invalid_quantities_and_unknown_references():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        invalid_reserved = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 2, "reserved_quantity": 3, "source": "ERP",
        })
        assert invalid_reserved.status_code == 422

        unknown_product = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": 9999,
            "on_hand_quantity": 2, "source": "ERP",
        })
        assert unknown_product.status_code == 404


def test_duplicate_external_reference_is_rejected():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        payload = {
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 10, "source": "ERP",
            "external_reference": "BATCH-77",
        }
        assert client.post("/api/v1/inventory/snapshots", json=payload).status_code == 201
        assert client.post("/api/v1/inventory/snapshots", json=payload).status_code == 409


def test_inventory_snapshot_rejects_non_finite_and_out_of_range_quantities():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        base = {
            "store_id": store_id,
            "product_id": product_id,
            "on_hand_quantity": 10,
            "reserved_quantity": 0,
            "source": "ERP",
        }
        invalid_payloads = [
            {**base, "on_hand_quantity": float("nan")},
            {**base, "on_hand_quantity": float("inf")},
            {**base, "reserved_quantity": float("inf")},
            {**base, "on_hand_quantity": 1_000_000_000},
            {**base, "reserved_quantity": 1_000_000_000},
        ]

        for payload in invalid_payloads:
            response = client.post("/api/v1/inventory/snapshots", json=payload)
            assert response.status_code == 422, response.text

        history = client.get("/api/v1/inventory/snapshots", params={"store_id": store_id})
        assert history.status_code == 200
        assert history.json() == []


def test_inventory_snapshot_rejects_blank_or_control_character_external_reference():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        base = {
            "store_id": store_id,
            "product_id": product_id,
            "on_hand_quantity": 10,
            "source": "ERP",
        }

        for reference in ("", "   ", "ERP-" + chr(10) + "-001", "ERP-" + chr(9) + "-001", "ERP-" + chr(127) + "-001"):
            response = client.post(
                "/api/v1/inventory/snapshots",
                json={**base, "external_reference": reference},
            )
            assert response.status_code == 422, response.text

        normalized = client.post(
            "/api/v1/inventory/snapshots",
            json={**base, "external_reference": "  ERP-BATCH-001  "},
        )
        assert normalized.status_code == 201, normalized.text
        assert normalized.json()["external_reference"] == "ERP-BATCH-001"


def test_replenishment_recommendation_uses_observation_and_backroom_stock():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Bebidas",
        })
        shelf = client.post("/api/v1/shelves", json={
            "zone_id": zone.json()["id"], "code": "BEB-01",
        })
        shelf_id = shelf.json()["id"]

        assignment = client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf_id, "product_id": product_id,
            "target_quantity": 12, "min_display_quantity": 4,
        })
        assert assignment.status_code == 201

        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "LOW_STOCK", "confidence": 0.91,
        })
        assert observation.status_code == 201

        inventory = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 25, "reserved_quantity": 5,
            "source": "ERP",
        })
        assert inventory.status_code == 201

        response = client.get(
            "/api/v1/replenishment/recommendations",
            params={"store_id": store_id},
        )
        assert response.status_code == 200
        recommendation = response.json()[0]
        assert recommendation["recommendation_status"] == "NEEDS_REPLENISHMENT"
        assert recommendation["inventory_available_quantity"] == 20
        assert recommendation["suggested_quantity"] is None


def test_replenishment_does_not_recommend_when_backroom_is_empty():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Mercearia",
        })
        shelf = client.post("/api/v1/shelves", json={
            "zone_id": zone.json()["id"], "code": "MER-01",
        })
        shelf_id = shelf.json()["id"]
        client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf_id, "product_id": product_id,
            "target_quantity": 10, "min_display_quantity": 2,
        })
        client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "status": "EMPTY", "confidence": 0.95,
        })
        client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 0, "reserved_quantity": 0,
            "source": "WMS",
        })

        response = client.get(
            "/api/v1/replenishment/recommendations",
            params={"store_id": store_id},
        )
        assert response.status_code == 200
        assert response.json()[0]["recommendation_status"] == "BACKROOM_OUT_OF_STOCK"


def test_measured_shelf_quantity_produces_capped_refill_recommendation():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Mercearia"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "MER-02"})
        shelf_id = shelf.json()["id"]
        client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf_id, "product_id": product_id,
            "target_quantity": 12, "min_display_quantity": 3,
        })
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation", "status": "LOW_STOCK",
            "confidence": 0.93, "observed_quantity": 2,
        })
        assert observation.status_code == 201
        assert observation.json()["observed_quantity"] == 2

        client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 25, "reserved_quantity": 5, "source": "ERP",
        })
        response = client.get("/api/v1/replenishment/recommendations", params={"store_id": store_id})
        recommendation = response.json()[0]
        assert recommendation["observed_shelf_quantity"] == 2
        assert recommendation["recommendation_status"] == "NEEDS_REPLENISHMENT"
        assert recommendation["suggested_quantity"] == 10


def test_measured_shelf_refill_is_capped_by_backroom_availability():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Bebidas"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "BEB-02"})
        shelf_id = shelf.json()["id"]
        client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf_id, "product_id": product_id,
            "target_quantity": 12, "min_display_quantity": 3,
        })
        client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "status": "EMPTY", "confidence": 0.98,
            "observed_quantity": 0,
        })
        client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 4, "reserved_quantity": 0, "source": "WMS",
        })

        response = client.get("/api/v1/replenishment/recommendations", params={"store_id": store_id})
        recommendation = response.json()[0]
        assert recommendation["suggested_quantity"] == 4
        assert "parcial" in recommendation["explanation"].lower()


def test_observation_rejects_negative_measured_shelf_quantity():
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "OBS-QTY", "name": "Loja observação"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Teste"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "OBS-QTY-01"})
        response = client.post("/api/v1/observations", json={
            "shelf_id": shelf.json()["id"], "status": "LOW_STOCK",
            "confidence": 0.9, "observed_quantity": -1,
        })
        assert response.status_code == 422



def _supervisor_actor(store_id: int, role: str = "SUPERVISOR"):
    db = TestingSession()
    try:
        user = models.User(
            email=f"{role.lower()}-{uuid4().hex}@example.test",
            store_id=store_id,
            full_name=f"CI {role}",
            password_hash="test-only-not-used",
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _completed_replenishment(client, *, snapshot_age_minutes: int = 5, on_hand: float = 20, reserved: float = 2):
    store_id, product_id = create_store_and_product(client)
    zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Reposição"})
    shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": f"REC-{uuid4().hex[:6]}"})
    shelf_id = shelf.json()["id"]
    client.post("/api/v1/shelf-products", json={
        "shelf_id": shelf_id, "product_id": product_id,
        "target_quantity": 12, "min_display_quantity": 2,
    })
    snapshot_time = datetime.now(timezone.utc) - timedelta(minutes=snapshot_age_minutes)
    snapshot = client.post("/api/v1/inventory/snapshots", json={
        "store_id": store_id, "product_id": product_id,
        "on_hand_quantity": on_hand, "reserved_quantity": reserved,
        "source": "WMS", "external_reference": f"REC-SRC-{uuid4().hex[:8]}",
        "captured_at": snapshot_time.isoformat(),
    })
    assert snapshot.status_code == 201, snapshot.text
    created = client.post("/api/v1/tasks", json={
        "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        "requested_quantity": 5,
    })
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    assert client.patch(f"/api/v1/tasks/{task_id}/status", json={
        "status": "ASSIGNED", "assigned_to": "operador",
    }).status_code == 200
    assert client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "IN_PROGRESS"}).status_code == 200
    completed = client.patch(f"/api/v1/tasks/{task_id}/status", json={
        "status": "COMPLETED",
        "actual_quantity": 4,
        "exception_reason": "Reposição parcial confirmada para o teste.",
    })
    assert completed.status_code == 200, completed.text
    return store_id, product_id, task_id, snapshot.json()["id"]


def test_reconciliation_creates_immutable_movement_and_result_snapshot(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id, task_id, source_snapshot_id = _completed_replenishment(client)
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
        response = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Reposição física confirmada pelo supervisor."},
        )
        assert response.status_code == 201, response.text
        movement = response.json()
        assert movement["task_id"] == task_id
        assert movement["quantity"] == 4
        assert movement["source_snapshot_id"] == source_snapshot_id
        assert movement["movement_type"] == "BACKROOM_TO_SHELF"

        history = client.get("/api/v1/inventory/snapshots", params={
            "store_id": store_id, "product_id": product_id,
        })
        assert history.status_code == 200
        snapshots = history.json()
        assert len(snapshots) == 2
        original = next(item for item in snapshots if item["id"] == source_snapshot_id)
        result = next(item for item in snapshots if item["id"] == movement["result_snapshot_id"])
        assert original["on_hand_quantity"] == 20
        assert result["on_hand_quantity"] == 16
        assert result["reserved_quantity"] == 2
        assert result["available_quantity"] == 14

        events = client.get(f"/api/v1/tasks/{task_id}/events")
        assert events.status_code == 200
        assert events.json()[-1]["event_type"] == "INVENTORY_RECONCILED"
        assert "snapshot_origem=" in events.json()[-1]["reason"]


def test_reconciliation_is_idempotent_and_requires_supervisor(monkeypatch):
    with TestClient(app) as client:
        store_id, _, task_id, _ = _completed_replenishment(client)
        employee = _supervisor_actor(store_id, role="EMPLOYEE")
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: employee)
        forbidden = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Tentativa sem autorização"},
        )
        assert forbidden.status_code == 403
        supervisor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: supervisor)
        assert client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Aprovado pelo supervisor"},
        ).status_code == 201
        duplicate = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Repetição idempotente"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "INVENTORY_ALREADY_RECONCILED"


def test_reconciliation_rejects_stale_inventory_snapshot(monkeypatch):
    with TestClient(app) as client:
        store_id, _, task_id, _ = _completed_replenishment(client, snapshot_age_minutes=300)
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
        response = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Teste de evidência antiga"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "INVENTORY_SNAPSHOT_STALE"


def test_reconciliation_rejects_inventory_snapshot_newer_than_task_completion(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id, task_id, _ = _completed_replenishment(client)
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
        newer = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 15, "reserved_quantity": 0,
            "source": "ERP", "external_reference": f"AFTER-{uuid4().hex[:8]}",
            "captured_at": (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
        })
        assert newer.status_code == 201, newer.text
        response = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Snapshot posterior à tarefa"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "INVENTORY_EVIDENCE_AFTER_TASK"


def test_reconciliation_rejects_insufficient_available_backroom_stock(monkeypatch):
    with TestClient(app) as client:
        store_id, _, task_id, _ = _completed_replenishment(client, on_hand=5, reserved=2)
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
        response = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Stock disponível insuficiente"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "INSUFFICIENT_BACKROOM_STOCK"


def test_reconciliation_requires_authenticated_approver(monkeypatch):
    with TestClient(app) as client:
        store_id, _, task_id, _ = _completed_replenishment(client)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: None)
        response = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Sem utilizador autenticado"},
        )
        assert response.status_code == 401



def test_inventory_history_and_latest_enforce_store_scope_for_supervisor(monkeypatch):
    with TestClient(app) as client:
        own_store_id, own_product_id = create_store_and_product(client)
        foreign_store = client.post("/api/v1/stores", json={
            "code": "INV-FOREIGN", "name": "Loja externa",
        })
        assert foreign_store.status_code == 201
        foreign_store_id = foreign_store.json()["id"]
        foreign_product = client.post("/api/v1/products", json={
            "sku": "INV-FOREIGN-SKU", "name": "Produto externo",
        })
        foreign_product_id = foreign_product.json()["id"]

        own_snapshot = client.post("/api/v1/inventory/snapshots", json={
            "store_id": own_store_id, "product_id": own_product_id,
            "on_hand_quantity": 12, "reserved_quantity": 2, "source": "ERP",
        })
        foreign_snapshot = client.post("/api/v1/inventory/snapshots", json={
            "store_id": foreign_store_id, "product_id": foreign_product_id,
            "on_hand_quantity": 30, "reserved_quantity": 5, "source": "WMS",
        })
        assert own_snapshot.status_code == 201
        assert foreign_snapshot.status_code == 201

        actor = _supervisor_actor(own_store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

        own_history = client.get("/api/v1/inventory/snapshots", params={
            "store_id": own_store_id, "product_id": own_product_id,
        })
        assert own_history.status_code == 200
        assert [item["id"] for item in own_history.json()] == [own_snapshot.json()["id"]]

        foreign_history = client.get("/api/v1/inventory/snapshots", params={
            "store_id": foreign_store_id, "product_id": foreign_product_id,
        })
        assert foreign_history.status_code == 403

        own_latest = client.get("/api/v1/inventory/latest", params={
            "store_id": own_store_id, "product_id": own_product_id,
        })
        assert own_latest.status_code == 200
        assert own_latest.json()["id"] == own_snapshot.json()["id"]

        foreign_latest = client.get("/api/v1/inventory/latest", params={
            "store_id": foreign_store_id, "product_id": foreign_product_id,
        })
        assert foreign_latest.status_code == 403

        implicit_store_history = client.get("/api/v1/inventory/snapshots")
        assert implicit_store_history.status_code == 200
        assert all(item["store_id"] == own_store_id for item in implicit_store_history.json())
