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


def create_store_and_product(client, *, unit: str = "un"):
    suffix = uuid4().hex[:8].upper()
    store = client.post("/api/v1/stores", json={"code": f"INV-{suffix}", "name": "Loja inventário"})
    product = client.post("/api/v1/products", json={"sku": f"INV-SKU-{suffix}", "name": "Arroz 1 kg", "unit": unit})
    assert store.status_code == 201, store.text
    assert product.status_code == 201, product.text
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
            "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
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
            {**base, "on_hand_quantity": "NaN"},
            {**base, "on_hand_quantity": "Infinity"},
            {**base, "reserved_quantity": "Infinity"},
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

        _configure_backroom_location(store_id)
        inventory = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 25, "reserved_quantity": 5,
            "source": "WMS", "location_code": "BACKROOM-A",
            "availability_status": "AVAILABLE",
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


def test_replenishment_blocks_future_dated_observation(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Zona relógio",
        }).json()
        shelf = client.post("/api/v1/shelves", json={
            "zone_id": zone["id"], "code": "FUTURE-REPLENISH",
        }).json()
        assignment = client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "target_quantity": 10, "min_display_quantity": 2,
        })
        assert assignment.status_code == 201, assignment.text

        reference_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "status": "LOW_STOCK", "source": "mobile",
            "confidence": 0.99, "observed_quantity": 0,
            "observed_at": (reference_time + timedelta(minutes=5)).isoformat(),
        })
        assert observation.status_code == 201, observation.text
        inventory = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 20, "reserved_quantity": 0, "source": "ERP",
        })
        assert inventory.status_code == 201, inventory.text

        monkeypatch.setattr(main_module.models, "utc_now", lambda: reference_time)
        response = client.get(
            "/api/v1/replenishment/recommendations",
            params={"store_id": store_id},
        )
        assert response.status_code == 200, response.text
        recommendation = response.json()[0]
        assert recommendation["recommendation_status"] == "INVALID_OBSERVATION_TIMESTAMP"
        assert recommendation["suggested_quantity"] is None
        assert "futuro" in recommendation["explanation"].lower()


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
        _configure_backroom_location(store_id)
        client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 0, "reserved_quantity": 0,
            "source": "WMS", "location_code": "BACKROOM-A",
            "availability_status": "AVAILABLE",
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

        _configure_backroom_location(store_id)
        client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 25, "reserved_quantity": 5, "source": "WMS",
            "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
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
        _configure_backroom_location(store_id)
        client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 4, "reserved_quantity": 0, "source": "WMS",
            "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
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


def _configure_backroom_location(store_id: int, location_code: str = "BACKROOM-A", max_age_minutes: int = 240):
    with TestingSession() as db:
        policy = db.query(models.InventoryFreshnessPolicy).filter_by(
            store_id=store_id, source="WMS",
        ).first()
        if policy is None:
            policy = models.InventoryFreshnessPolicy(
                store_id=store_id,
                source="WMS",
                max_age_minutes=max_age_minutes,
                backroom_location_code=location_code,
            )
            db.add(policy)
        else:
            policy.max_age_minutes = max_age_minutes
            policy.backroom_location_code = location_code
        db.commit()


def _completed_replenishment(
    client, *, snapshot_age_minutes: int = 5, on_hand: float = 20,
    reserved: float = 2, unit: str = "un", actual_quantity: float = 4,
):
    store_id, product_id = create_store_and_product(client, unit=unit)
    zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Reposição"})
    shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": f"REC-{uuid4().hex[:6]}"})
    shelf_id = shelf.json()["id"]
    client.post("/api/v1/shelf-products", json={
        "shelf_id": shelf_id, "product_id": product_id,
        "target_quantity": 12, "min_display_quantity": 2,
    })
    _configure_backroom_location(store_id)
    snapshot_time = datetime.now(timezone.utc) - timedelta(minutes=snapshot_age_minutes)
    snapshot = client.post("/api/v1/inventory/snapshots", json={
        "store_id": store_id, "product_id": product_id,
        "on_hand_quantity": on_hand, "reserved_quantity": reserved,
        "source": "WMS", "external_reference": f"REC-SRC-{uuid4().hex[:8]}",
        "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
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
        "actual_quantity": actual_quantity,
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
        assert movement["operation_id"]
        assert movement["source_location_code"] == "BACKROOM-A"
        assert movement["destination_shelf_id"] is not None
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
            "source": "WMS", "external_reference": f"AFTER-{uuid4().hex[:8]}",
            "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
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
            "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
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


def test_sales_csv_imports_are_store_scoped_and_rejected_foreign_imports_are_atomic(monkeypatch):
    with TestClient(app) as client:
        own_store_id, product_id = create_store_and_product(client)
        foreign_store = client.post("/api/v1/stores", json={
            "code": "INV-CSV-FOREIGN", "name": "Loja externa CSV",
        })
        assert foreign_store.status_code == 201
        foreign_store_id = foreign_store.json()["id"]
        actor = _supervisor_actor(own_store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

        daily_csv = (
            "product_id,sales_date,quantity,external_reference\n"
            f"{product_id},2026-11-20,3,DAILY-OWN-001\n"
        ).encode()
        own_daily = client.post(
            "/api/v1/sales/import-csv",
            data={"store_id": str(own_store_id), "source": "IMPORT"},
            files={"file": ("daily.csv", daily_csv, "text/csv")},
        )
        assert own_daily.status_code == 200, own_daily.text
        assert own_daily.json()["rows_imported"] == 1

        hourly_sales_csv = (
            "product_id,business_date,hour_of_day,quantity,external_reference\n"
            f"{product_id},2026-11-20,9,2,HOURLY-OWN-001\n"
        ).encode()
        own_hourly = client.post(
            "/api/v1/sales/hourly/import-csv",
            data={"store_id": str(own_store_id), "source": "IMPORT"},
            files={"file": ("hourly.csv", hourly_sales_csv, "text/csv")},
        )
        assert own_hourly.status_code == 200, own_hourly.text

        traffic_csv = (
            "business_date,hour_of_day,customer_count,external_reference\n"
            "2026-11-20,9,12,TRAFFIC-OWN-001\n"
        ).encode()
        own_traffic = client.post(
            "/api/v1/sales/traffic/hourly/import-csv",
            data={"store_id": str(own_store_id), "source": "IMPORT"},
            files={"file": ("traffic.csv", traffic_csv, "text/csv")},
        )
        assert own_traffic.status_code == 200, own_traffic.text

        with TestingSession() as db:
            before = (
                db.query(models.DailySalesRecord).count(),
                db.query(models.HourlySalesRecord).count(),
                db.query(models.HourlyStoreTrafficRecord).count(),
            )

        foreign_requests = [
            client.post(
                "/api/v1/sales/import-csv",
                data={"store_id": str(foreign_store_id), "source": "IMPORT"},
                files={"file": ("daily.csv", daily_csv, "text/csv")},
            ),
            client.post(
                "/api/v1/sales/hourly/import-csv",
                data={"store_id": str(foreign_store_id), "source": "IMPORT"},
                files={"file": ("hourly.csv", hourly_sales_csv, "text/csv")},
            ),
            client.post(
                "/api/v1/sales/traffic/hourly/import-csv",
                data={"store_id": str(foreign_store_id), "source": "IMPORT"},
                files={"file": ("traffic.csv", traffic_csv, "text/csv")},
            ),
        ]
        assert [response.status_code for response in foreign_requests] == [403, 403, 403]

        with TestingSession() as db:
            after = (
                db.query(models.DailySalesRecord).count(),
                db.query(models.HourlySalesRecord).count(),
                db.query(models.HourlyStoreTrafficRecord).count(),
            )
        assert after == before


def test_foreign_pallet_rotation_policy_id_is_hidden_and_cannot_be_mutated(monkeypatch):
    from types import SimpleNamespace

    with TestingSession() as db:
        store_a = models.Store(code=f"POLICY-A-{uuid4().hex[:8]}", name="Policy tenant A")
        store_b = models.Store(code=f"POLICY-B-{uuid4().hex[:8]}", name="Policy tenant B")
        product = models.Product(
            sku=f"POLICY-SKU-{uuid4().hex[:8]}",
            name="Global catalogue product",
            is_active=True,
        )
        db.add_all([store_a, store_b, product])
        db.flush()
        own_policy = models.PalletRotationPolicy(
            store_id=store_a.id,
            product_id=product.id,
            threshold_ratio=0.5,
            is_enabled=True,
        )
        foreign_policy = models.PalletRotationPolicy(
            store_id=store_b.id,
            product_id=product.id,
            threshold_ratio=0.5,
            is_enabled=True,
        )
        db.add_all([own_policy, foreign_policy])
        db.commit()
        own_policy_id = own_policy.id
        foreign_policy_id = foreign_policy.id
        store_a_id = store_a.id

    actor = SimpleNamespace(
        id=987654,
        role="SUPERVISOR",
        store_id=store_a_id,
        is_active=True,
    )
    monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

    with TestClient(app) as client:
        foreign = client.patch(
            f"/api/v1/warehouse/pallet-rotation/policies/{foreign_policy_id}",
            json={"is_enabled": False},
        )
        missing = client.patch(
            "/api/v1/warehouse/pallet-rotation/policies/2147483000",
            json={"is_enabled": False},
        )
        own = client.patch(
            f"/api/v1/warehouse/pallet-rotation/policies/{own_policy_id}",
            json={"is_enabled": False},
        )

    assert foreign.status_code == 404, foreign.text
    assert missing.status_code == 404, missing.text
    assert own.status_code == 200, own.text
    assert own.json()["is_enabled"] is False

    with TestingSession() as db:
        persisted_foreign = db.get(models.PalletRotationPolicy, foreign_policy_id)
        assert persisted_foreign is not None
        assert persisted_foreign.is_enabled is True


def test_reconciliation_hides_foreign_and_missing_task_ids(monkeypatch):
    with TestClient(app) as client:
        own_store_id, _, _, _ = _completed_replenishment(client)
        _, _, foreign_task_id, _ = _completed_replenishment(client)
        actor = _supervisor_actor(own_store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)

        foreign = client.post(
            f"/api/v1/tasks/{foreign_task_id}/reconcile-inventory",
            json={"reason": "Tentativa de reconciliação cross-store."},
        )
        missing = client.post(
            "/api/v1/tasks/2147483000/reconcile-inventory",
            json={"reason": "Tentativa de reconciliação cross-store."},
        )
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()

        with TestingSession() as db:
            assert db.query(models.InventoryMovement).filter_by(task_id=foreign_task_id).count() == 0


def test_inventory_movement_history_is_scoped_filterable_and_read_only(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id, task_id, _ = _completed_replenishment(client)
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

        reconciled = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Reposição validada para histórico."},
        )
        assert reconciled.status_code == 201, reconciled.text
        movement_id = reconciled.json()["id"]

        history = client.get(
            "/api/v1/inventory/movements",
            params={"store_id": store_id},
        )
        assert history.status_code == 200, history.text
        assert [item["id"] for item in history.json()] == [movement_id]
        assert history.json()[0]["task_id"] == task_id
        assert history.json()[0]["product_id"] == product_id

        by_task = client.get(
            "/api/v1/inventory/movements",
            params={"store_id": store_id, "task_id": task_id},
        )
        assert by_task.status_code == 200
        assert [item["id"] for item in by_task.json()] == [movement_id]

        by_other_product = client.get(
            "/api/v1/inventory/movements",
            params={"store_id": store_id, "product_id": product_id + 99999},
        )
        assert by_other_product.status_code == 200
        assert by_other_product.json() == []

        with TestingSession() as db:
            before = db.query(models.InventoryMovement).count()
        assert before == 1


def test_inventory_movement_history_rejects_employee_and_foreign_store(monkeypatch):
    with TestClient(app) as client:
        store_id, _, _, _ = _completed_replenishment(client)
        foreign_store_id, _, _, _ = _completed_replenishment(client)

        employee = _supervisor_actor(store_id, role="EMPLOYEE")
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: employee)
        forbidden_role = client.get(
            "/api/v1/inventory/movements",
            params={"store_id": store_id},
        )
        assert forbidden_role.status_code == 403

        supervisor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: supervisor)
        foreign_store = client.get(
            "/api/v1/inventory/movements",
            params={"store_id": foreign_store_id},
        )
        assert foreign_store.status_code == 403


def test_inventory_reconciliation_separates_shelf_observation_from_backroom_stock(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Bebidas"}).json()
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone["id"], "code": "BEB-RECON"}).json()
        link = client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "target_quantity": 12, "min_display_quantity": 3,
        })
        assert link.status_code == 201, link.text
        reference_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "status": "LOW_STOCK", "source": "mobile",
            "confidence": 0.96, "observed_quantity": 4,
            "observed_at": (reference_time - timedelta(minutes=90)).isoformat(),
        })
        assert observation.status_code == 201, observation.text
        _configure_backroom_location(store_id)
        snapshot = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 30, "reserved_quantity": 5,
            "source": "WMS", "external_reference": f"RECON-{uuid4().hex[:8]}",
            "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
        })
        assert snapshot.status_code == 201, snapshot.text

        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
        monkeypatch.setattr(main_module.models, "utc_now", lambda: reference_time)
        response = client.get(f"/api/v1/inventory/reconciliation?store_id={store_id}")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["count"] == 1
        item = payload["items"][0]
        assert item["display_target_quantity"] == 12
        assert item["observed_shelf_quantity"] == 4
        assert item["display_delta"] == -8
        assert item["display_status"] == "BELOW_TARGET"
        assert item["observation_age_minutes"] == 90
        assert item["observation_timestamp_in_future"] is False
        assert item["backroom_on_hand_quantity"] == 30
        assert item["backroom_reserved_quantity"] == 5
        assert item["backroom_available_quantity"] == 25
        assert item["backroom_snapshot_id"] == snapshot.json()["id"]


def test_inventory_reconciliation_flags_future_dated_observation(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Zona com relógio divergente",
        }).json()
        shelf = client.post("/api/v1/shelves", json={
            "zone_id": zone["id"], "code": "FUTURE-OBS",
        }).json()
        assignment = client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "target_quantity": 10, "min_display_quantity": 2,
        })
        assert assignment.status_code == 201, assignment.text
        observation_time = datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)
        created = client.post("/api/v1/observations", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "status": "LOW_STOCK", "source": "mobile",
            "confidence": 0.95, "observed_quantity": 2,
            "observed_at": observation_time.isoformat(),
        })
        assert created.status_code == 201, created.text

        reference_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
        monkeypatch.setattr(main_module.models, "utc_now", lambda: reference_time)
        response = client.get(
            "/api/v1/inventory/reconciliation",
            params={"store_id": store_id},
        )
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["observation_age_minutes"] == 0
        assert item["observation_timestamp_in_future"] is True


def test_inventory_reconciliation_compares_fresh_erp_and_wms_snapshots(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Zona ERP WMS",
        }).json()
        shelf = client.post("/api/v1/shelves", json={
            "zone_id": zone["id"], "code": "ERP-WMS-01",
        }).json()
        linked = client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "target_quantity": 10, "min_display_quantity": 2,
        })
        assert linked.status_code == 201, linked.text

        erp = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 30, "reserved_quantity": 5,
            "source": "ERP", "external_reference": "ERP-CHECK-01",
        })
        wms = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 26, "reserved_quantity": 3,
            "source": "WMS", "external_reference": "WMS-CHECK-01",
            "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
        })
        assert erp.status_code == 201, erp.text
        assert wms.status_code == 201, wms.text
        _configure_backroom_location(store_id)

        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
        response = client.get(
            "/api/v1/inventory/reconciliation",
            params={"store_id": store_id},
        )
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["erp_snapshot_id"] == erp.json()["id"]
        assert item["wms_snapshot_id"] == wms.json()["id"]
        assert item["erp_available_quantity"] == 25
        assert item["wms_available_quantity"] == 23
        assert item["erp_freshness_status"] == "CURRENT"
        assert item["wms_freshness_status"] == "CURRENT"
        assert item["wms_erp_available_delta"] == -2
        assert item["wms_erp_comparison_status"] == "DIVERGENCE"

        with TestingSession() as db:
            assert db.query(models.InventoryMovement).count() == 0
            assert db.query(models.InventorySnapshot).count() == 2



def test_inventory_reconciliation_isolates_shared_product_snapshots_and_ledger_across_stores(monkeypatch):
    with TestClient(app) as client:
        store_a_id, product_id = create_store_and_product(client)
        store_b_response = client.post("/api/v1/stores", json={
            "code": f"INV-B-{uuid4().hex[:8].upper()}",
            "name": "Loja inventário B",
        })
        assert store_b_response.status_code == 201, store_b_response.text
        store_b_id = store_b_response.json()["id"]

        shelves = {}
        for store_id, suffix in ((store_a_id, "A"), (store_b_id, "B")):
            zone = client.post("/api/v1/zones", json={
                "store_id": store_id, "name": f"Zona {suffix}",
            })
            assert zone.status_code == 201, zone.text
            shelf = client.post("/api/v1/shelves", json={
                "zone_id": zone.json()["id"], "code": f"SHARED-{suffix}",
            })
            assert shelf.status_code == 201, shelf.text
            link = client.post("/api/v1/shelf-products", json={
                "shelf_id": shelf.json()["id"], "product_id": product_id,
                "target_quantity": 10, "min_display_quantity": 2,
            })
            assert link.status_code == 201, link.text
            shelves[store_id] = shelf.json()["id"]

        snapshot_ids = {}
        for store_id, marker in ((store_a_id, "A"), (store_b_id, "B")):
            _configure_backroom_location(store_id)
            erp = client.post("/api/v1/inventory/snapshots", json={
                "store_id": store_id, "product_id": product_id,
                "on_hand_quantity": 100 if marker == "A" else 900,
                "reserved_quantity": 10, "source": "ERP",
                "external_reference": f"SHARED-ERP-{marker}",
            })
            wms = client.post("/api/v1/inventory/snapshots", json={
                "store_id": store_id, "product_id": product_id,
                "on_hand_quantity": 80 if marker == "A" else 800,
                "reserved_quantity": 5, "source": "WMS",
                "external_reference": f"SHARED-WMS-{marker}",
                "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
            })
            assert erp.status_code == 201, erp.text
            assert wms.status_code == 201, wms.text
            snapshot_ids[store_id] = (erp.json()["id"], wms.json()["id"])

        actors = {
            store_a_id: _supervisor_actor(store_a_id),
            store_b_id: _supervisor_actor(store_b_id),
        }
        reconciliation_ids = {}
        for store_id in (store_a_id, store_b_id):
            monkeypatch.setattr(
                main_module, "_request_user",
                lambda _db, _request, actor=actors[store_id]: actor,
            )
            created = client.post("/api/v1/inventory/reconciliations", json={
                "store_id": store_id, "shelf_id": shelves[store_id],
                "product_id": product_id,
                "reason": "Verificação de isolamento entre lojas",
            })
            assert created.status_code == 201, created.text
            record = created.json()
            reconciliation_ids[store_id] = record["id"]
            assert (record["erp_snapshot_id"], record["wms_snapshot_id"]) == snapshot_ids[store_id]
            expected_erp = 90 if store_id == store_a_id else 890
            expected_wms = 75 if store_id == store_a_id else 795
            assert record["erp_available_quantity"] == expected_erp
            assert record["wms_available_quantity"] == expected_wms

        actor_a = actors[store_a_id]
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor_a)
        current = client.get(
            "/api/v1/inventory/reconciliation",
            params={"store_id": store_a_id},
        )
        assert current.status_code == 200, current.text
        assert current.json()["count"] == 1
        assert current.json()["items"][0]["store_id"] == store_a_id
        assert current.json()["items"][0]["erp_snapshot_id"] == snapshot_ids[store_a_id][0]

        own_ledger = client.get(
            "/api/v1/inventory/reconciliations",
            params={"store_id": store_a_id},
        )
        assert own_ledger.status_code == 200, own_ledger.text
        assert own_ledger.json()["count"] == 1
        assert own_ledger.json()["items"][0]["id"] == reconciliation_ids[store_a_id]

        foreign_review = client.post(
            f"/api/v1/inventory/reconciliations/{reconciliation_ids[store_b_id]}/review",
            json={"decision": "APPROVED", "reason": "Tentativa cross-store"},
        )
        assert foreign_review.status_code == 404, foreign_review.text

        with TestingSession() as db:
            foreign_record = db.get(
                models.InventoryReconciliation, reconciliation_ids[store_b_id]
            )
            assert foreign_record is not None
            assert foreign_record.review_status == "PENDING"
            assert db.query(models.InventoryMovement).count() == 0


def test_inventory_reconciliation_rejects_employee_and_foreign_store(monkeypatch):
    with TestClient(app) as client:
        store_id, _ = create_store_and_product(client)
        employee = _supervisor_actor(store_id, role="EMPLOYEE")
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: employee)
        denied = client.get(f"/api/v1/inventory/reconciliation?store_id={store_id}")
        assert denied.status_code == 403

        supervisor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: supervisor)
        foreign = client.get(f"/api/v1/inventory/reconciliation?store_id={store_id + 999}")
        assert foreign.status_code == 403

def test_inventory_reconciliation_keeps_missing_evidence_unknown_and_read_only(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post(
            "/api/v1/zones",
            json={"store_id": store_id, "name": "Zona sem evidência"},
        ).json()
        shelf = client.post(
            "/api/v1/shelves",
            json={"zone_id": zone["id"], "code": "SEM-EVIDENCIA"},
        ).json()
        link = client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf["id"],
            "product_id": product_id,
            "target_quantity": 8,
            "min_display_quantity": 2,
        })
        assert link.status_code == 201, link.text

        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
        response = client.get(
            "/api/v1/inventory/reconciliation",
            params={"store_id": store_id},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["count"] == 1
        item = payload["items"][0]

        # Missing evidence is not evidence of zero stock.
        assert item["display_status"] == "NO_OBSERVATION"
        assert item["observed_shelf_quantity"] is None
        assert item["display_delta"] is None
        assert item["observation_age_minutes"] is None
        assert item["backroom_snapshot_id"] is None
        assert item["backroom_on_hand_quantity"] is None
        assert item["backroom_reserved_quantity"] is None
        assert item["backroom_available_quantity"] is None
        assert item["backroom_snapshot_age_minutes"] is None

        # A read-only reconciliation must not create accounting movements or snapshots.
        with TestingSession() as db:
            assert db.query(models.InventoryMovement).count() == 0
            assert db.query(models.InventorySnapshot).count() == 0



def test_inventory_reconciliation_ledger_persists_evidence_and_requires_independent_review(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Ledger auditável"}).json()
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone["id"], "code": "LEDGER-01"}).json()
        linked = client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "target_quantity": 12, "min_display_quantity": 2,
        })
        assert linked.status_code == 201, linked.text
        erp = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id, "on_hand_quantity": 40,
            "reserved_quantity": 5, "source": "ERP", "external_reference": "LEDGER-ERP-01",
        })
        wms = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id, "on_hand_quantity": 35,
            "reserved_quantity": 3, "source": "WMS", "external_reference": "LEDGER-WMS-01",
            "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
        })
        assert erp.status_code == 201, erp.text
        assert wms.status_code == 201, wms.text
        _configure_backroom_location(store_id)

        creator = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: creator)
        created = client.post("/api/v1/inventory/reconciliations", json={
            "store_id": store_id, "shelf_id": shelf["id"],
            "product_id": product_id, "reason": "Controlo periódico da loja",
        })
        assert created.status_code == 201, created.text
        record = created.json()
        assert record["review_status"] == "PENDING"
        assert record["created_by_user_id"] == creator.id
        assert record["erp_snapshot_id"] == erp.json()["id"]
        assert record["wms_snapshot_id"] == wms.json()["id"]
        assert record["erp_available_quantity"] == 35
        assert record["wms_available_quantity"] == 32
        assert record["wms_erp_delta"] == -3
        assert record["evidence"]["erp"]["captured_at"]
        assert [event["event_type"] for event in record["events"]] == ["CREATED"]

        self_review = client.post(
            f"/api/v1/inventory/reconciliations/{record['id']}/review",
            json={"decision": "APPROVED", "reason": "Validação própria"},
        )
        assert self_review.status_code == 409

        reviewer = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: reviewer)
        approved = client.post(
            f"/api/v1/inventory/reconciliations/{record['id']}/review",
            json={"decision": "APPROVED", "reason": "Divergência confirmada por contagem manual"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["review_status"] == "APPROVED"
        assert approved.json()["reviewed_by_user_id"] == reviewer.id
        assert [event["event_type"] for event in approved.json()["events"]] == ["CREATED", "APPROVED"]

        history = client.get("/api/v1/inventory/reconciliations", params={
            "store_id": store_id, "review_status": "APPROVED",
        })
        assert history.status_code == 200
        assert history.json()["count"] == 1
        with TestingSession() as db:
            assert db.query(models.InventoryMovement).count() == 0
            assert db.query(models.InventorySnapshot).count() == 2


def test_inventory_reconciliation_ledger_rejects_employee(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Zona restrita"}).json()
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone["id"], "code": "LEDGER-SEC"}).json()
        client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "target_quantity": 5, "min_display_quantity": 1,
        })
        employee = _supervisor_actor(store_id, role="EMPLOYEE")
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: employee)
        denied = client.post("/api/v1/inventory/reconciliations", json={
            "store_id": store_id, "shelf_id": shelf["id"],
            "product_id": product_id, "reason": "Pedido não autorizado",
        })
        assert denied.status_code == 403


def test_inventory_reconciliation_dashboard_aggregates_ledger_and_freshness(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Dashboard"}).json()
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone["id"], "code": "DASH-01"}).json()
        assert client.post("/api/v1/shelf-products", json={"shelf_id": shelf["id"], "product_id": product_id, "target_quantity": 10, "min_display_quantity": 2}).status_code == 201
        observation = client.post("/api/v1/observations", json={"shelf_id": shelf["id"], "product_id": product_id, "observed_quantity": 7, "source": "mobile"})
        _configure_backroom_location(store_id)
        erp = client.post("/api/v1/inventory/snapshots", json={"store_id": store_id, "product_id": product_id, "on_hand_quantity": 30, "reserved_quantity": 0, "source": "ERP", "external_reference": "DASH-ERP-01"})
        wms = client.post("/api/v1/inventory/snapshots", json={"store_id": store_id, "product_id": product_id, "on_hand_quantity": 25, "reserved_quantity": 0, "source": "WMS", "external_reference": "DASH-WMS-01", "location_code": "BACKROOM-A", "availability_status": "AVAILABLE"})
        assert observation.status_code == 201, observation.text
        assert erp.status_code == 201, erp.text
        assert wms.status_code == 201, wms.text
        creator = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: creator)
        for reason in ("Auditoria inicial", "Auditoria de seguimento"):
            created = client.post("/api/v1/inventory/reconciliations", json={"store_id": store_id, "shelf_id": shelf["id"], "product_id": product_id, "reason": reason})
            assert created.status_code == 201, created.text
        response = client.get("/api/v1/inventory/reconciliations/dashboard", params={"store_id": store_id})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total_reconciliations"] == 2
        assert payload["unique_products"] == 1
        assert payload["recurring_products_30d"] == 1
        assert payload["review_status_counts"]["PENDING"] == 2
        assert payload["product_ranking"][0]["is_recurring"] is True
        assert payload["source_freshness"]["ERP"]["current"] == 1
        assert payload["source_freshness"]["WMS"]["current"] == 1
        assert payload["source_freshness"]["SHELF"]["current"] == 1
        with TestingSession() as db:
            assert db.query(models.InventoryMovement).count() == 0


def test_inventory_reconciliation_dashboard_counts_each_shelf_and_flags_any_future_observation(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Duas exposições"}).json()
        shelves = [
            client.post("/api/v1/shelves", json={"zone_id": zone["id"], "code": "FRESH-01"}).json(),
            client.post("/api/v1/shelves", json={"zone_id": zone["id"], "code": "FRESH-02"}).json(),
        ]
        reference_time = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        for index, shelf in enumerate(shelves):
            linked = client.post("/api/v1/shelf-products", json={
                "shelf_id": shelf["id"], "product_id": product_id,
                "target_quantity": 10, "min_display_quantity": 2,
            })
            assert linked.status_code == 201, linked.text
            observed_at = reference_time - timedelta(minutes=10) if index == 0 else reference_time + timedelta(minutes=2)
            observation = client.post("/api/v1/observations", json={
                "shelf_id": shelf["id"], "product_id": product_id,
                "source": "mobile", "status": "LOW_STOCK",
                "confidence": 0.95, "observed_quantity": 2,
                "observed_at": observed_at.isoformat(),
            })
            assert observation.status_code == 201, observation.text

        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
        monkeypatch.setattr(main_module.models, "utc_now", lambda: reference_time)
        for shelf in shelves:
            created = client.post("/api/v1/inventory/reconciliations", json={
                "store_id": store_id, "shelf_id": shelf["id"],
                "product_id": product_id, "reason": "Verificação de exposição",
            })
            assert created.status_code == 201, created.text

        response = client.get(
            "/api/v1/inventory/reconciliations/dashboard",
            params={"store_id": store_id},
        )
        assert response.status_code == 200, response.text
        shelf_freshness = response.json()["source_freshness"]["SHELF"]
        assert shelf_freshness["current"] == 1
        assert shelf_freshness["future"] == 1
        assert shelf_freshness["coverage_percent"] == 100.0
        assert shelf_freshness["freshness_percent"] == 50.0


def test_inventory_reconciliation_dashboard_rejects_employee(monkeypatch):
    with TestClient(app) as client:
        store_id, _ = create_store_and_product(client)
        employee = _supervisor_actor(store_id, role="EMPLOYEE")
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: employee)
        response = client.get("/api/v1/inventory/reconciliations/dashboard", params={"store_id": store_id})
        assert response.status_code == 403



def test_inventory_source_sync_lifecycle_history_and_health(monkeypatch):
    with TestClient(app) as client:
        store_id, _ = create_store_and_product(client)
        supervisor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: supervisor)

        started = client.post("/api/v1/inventory/source-syncs", json={
            "store_id": store_id, "source": "ERP", "provider": "ERP-connector",
            "external_run_id": "erp-run-001",
        })
        assert started.status_code == 201, started.text
        attempt = started.json()
        assert attempt["status"] == "STARTED"
        assert attempt["events"][0]["event_type"] == "STARTED"

        completed = client.post(f"/api/v1/inventory/source-syncs/{attempt['id']}/complete", json={
            "status": "SUCCESS", "received_records": 120, "processed_records": 120,
        })
        assert completed.status_code == 200, completed.text
        result = completed.json()
        assert result["status"] == "SUCCESS"
        assert result["duration_ms"] is not None and result["duration_ms"] >= 0
        assert [event["event_type"] for event in result["events"]] == ["STARTED", "COMPLETED"]

        duplicate = client.post(f"/api/v1/inventory/source-syncs/{attempt['id']}/complete", json={
            "status": "SUCCESS", "received_records": 120, "processed_records": 120,
        })
        assert duplicate.status_code == 409

        failed = client.post("/api/v1/inventory/source-syncs", json={
            "store_id": store_id, "source": "WMS", "provider": "WMS-connector",
        })
        assert failed.status_code == 201, failed.text
        failed_result = client.post(f"/api/v1/inventory/source-syncs/{failed.json()['id']}/complete", json={
            "status": "FAILED", "received_records": 0, "processed_records": 0,
            "error_code": "UPSTREAM_TIMEOUT", "error_message": "O sistema WMS não respondeu dentro do prazo.",
        })
        assert failed_result.status_code == 200, failed_result.text

        history = client.get("/api/v1/inventory/source-syncs", params={"store_id": store_id})
        assert history.status_code == 200, history.text
        assert len(history.json()["items"]) == 2

        health = client.get("/api/v1/inventory/source-syncs/health", params={"store_id": store_id})
        assert health.status_code == 200, health.text
        assert health.json()["sources"]["ERP"]["stale"] is False
        assert health.json()["sources"]["WMS"]["stale"] is True
        assert health.json()["sources"]["WMS"]["alert_code"] == "SOURCE_NEVER_SYNCHRONIZED"
        assert health.json()["sources"]["WMS"]["latest_attempt_failed"] is True

        with TestingSession() as db:
            assert db.query(models.InventoryMovement).count() == 0


def test_inventory_source_sync_rejects_employee_and_invalid_completion(monkeypatch):
    with TestClient(app) as client:
        store_id, _ = create_store_and_product(client)
        employee = _supervisor_actor(store_id, role="EMPLOYEE")
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: employee)
        denied = client.post("/api/v1/inventory/source-syncs", json={
            "store_id": store_id, "source": "ERP", "provider": "ERP-connector",
        })
        assert denied.status_code == 403

        supervisor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: supervisor)
        started = client.post("/api/v1/inventory/source-syncs", json={
            "store_id": store_id, "source": "WMS", "provider": "WMS-connector",
        })
        assert started.status_code == 201, started.text
        invalid = client.post(f"/api/v1/inventory/source-syncs/{started.json()['id']}/complete", json={
            "status": "FAILED", "received_records": 1, "processed_records": 2,
        })
        assert invalid.status_code == 422



def test_erp_stock_never_substitutes_for_unconfigured_wms_backroom(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Sem localização WMS",
        }).json()
        shelf = client.post("/api/v1/shelves", json={
            "zone_id": zone["id"], "code": "ERP-NO-FALLBACK",
        }).json()
        client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "target_quantity": 12, "min_display_quantity": 2,
        })
        client.post("/api/v1/observations", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "status": "EMPTY", "confidence": 0.99, "observed_quantity": 0,
        })
        erp = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 80, "reserved_quantity": 0,
            "source": "ERP", "external_reference": "ERP-NO-BACKROOM",
        })
        assert erp.status_code == 201, erp.text

        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
        reconciliation = client.get(
            "/api/v1/inventory/reconciliation", params={"store_id": store_id},
        )
        assert reconciliation.status_code == 200, reconciliation.text
        item = reconciliation.json()["items"][0]
        assert item["erp_available_quantity"] == 80
        assert item["backroom_snapshot_id"] is None
        assert item["backroom_available_quantity"] is None
        assert item["wms_erp_comparison_status"] == "WMS_BACKROOM_LOCATION_NOT_CONFIGURED"

        recommendation = client.get(
            "/api/v1/replenishment/recommendations", params={"store_id": store_id},
        )
        assert recommendation.status_code == 200, recommendation.text
        assert recommendation.json()[0]["recommendation_status"] == "INVENTORY_UNKNOWN"
        assert recommendation.json()[0]["suggested_quantity"] is None
        assert "ERP não é substituto" in recommendation.json()[0]["explanation"]


def test_latest_unavailable_wms_record_shadows_older_available_stock(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Disponibilidade WMS",
        }).json()
        shelf = client.post("/api/v1/shelves", json={
            "zone_id": zone["id"], "code": "WMS-UNAVAILABLE",
        }).json()
        client.post("/api/v1/shelf-products", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "target_quantity": 12, "min_display_quantity": 2,
        })
        client.post("/api/v1/observations", json={
            "shelf_id": shelf["id"], "product_id": product_id,
            "status": "EMPTY", "confidence": 0.99, "observed_quantity": 0,
        })
        _configure_backroom_location(store_id)
        base = datetime.now(timezone.utc)
        older = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 50, "reserved_quantity": 0,
            "source": "WMS", "external_reference": "WMS-AVAILABLE-OLD",
            "location_code": "BACKROOM-A", "availability_status": "AVAILABLE",
            "captured_at": (base - timedelta(minutes=10)).isoformat(),
        })
        wrong_location = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 900, "reserved_quantity": 0,
            "source": "WMS", "external_reference": "WMS-WRONG-LOCATION",
            "location_code": "SALES-FLOOR", "availability_status": "AVAILABLE",
            "captured_at": (base + timedelta(seconds=1)).isoformat(),
        })
        latest = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 50, "reserved_quantity": 0,
            "source": "WMS", "external_reference": "WMS-UNAVAILABLE-NEW",
            "location_code": "BACKROOM-A", "availability_status": "UNAVAILABLE",
            "captured_at": base.isoformat(),
        })
        assert older.status_code == wrong_location.status_code == latest.status_code == 201
        assert latest.json()["available_quantity"] is None

        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
        reconciliation = client.get(
            "/api/v1/inventory/reconciliation", params={"store_id": store_id},
        )
        assert reconciliation.status_code == 200, reconciliation.text
        item = reconciliation.json()["items"][0]
        assert item["backroom_snapshot_id"] == latest.json()["id"]
        assert item["backroom_available_quantity"] is None
        assert item["wms_availability_status"] == "UNAVAILABLE"

        recommendation = client.get(
            "/api/v1/replenishment/recommendations", params={"store_id": store_id},
        )
        assert recommendation.status_code == 200, recommendation.text
        assert recommendation.json()[0]["recommendation_status"] == "INVENTORY_UNKNOWN"
        assert recommendation.json()[0]["suggested_quantity"] is None


def test_wms_backroom_location_is_configurable_per_store_through_policy_api(monkeypatch):
    with TestClient(app) as client:
        store_id, _ = create_store_and_product(client)
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

        configured = client.post("/api/v1/inventory/freshness-policies", json={
            "store_id": store_id, "source": "WMS", "max_age_minutes": 180,
            "backroom_location_code": "WH-BR-01",
            "reason": "Localização física validada pelo responsável da loja",
        })
        assert configured.status_code == 200, configured.text
        assert configured.json()["backroom_location_code"] == "WH-BR-01"

        listed = client.get(
            "/api/v1/inventory/freshness-policies", params={"store_id": store_id},
        )
        assert listed.status_code == 200, listed.text
        wms = next(item for item in listed.json() if item["source"] == "WMS")
        assert wms["backroom_location_code"] == "WH-BR-01"
        with TestingSession() as db:
            events = db.query(models.InventoryFreshnessPolicyEvent).filter_by(
                policy_id=wms["id"],
            ).all()
            assert len(events) == 1
            assert events[0].previous_backroom_location_code is None
            assert events[0].new_backroom_location_code == "WH-BR-01"
            assert events[0].actor_user_id == actor.id

        invalid = client.post("/api/v1/inventory/freshness-policies", json={
            "store_id": store_id, "source": "ERP", "max_age_minutes": 180,
            "backroom_location_code": "WH-BR-01",
        })
        assert invalid.status_code == 422


def test_inventory_movement_freezes_product_base_unit_and_exact_decimal_quantity(monkeypatch):
    with TestClient(app) as client:
        store_id, product_id, task_id, source_snapshot_id = _completed_replenishment(
            client, unit="kg", actual_quantity=2.375,
        )
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

        response = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Reposição pesada com quantidade decimal exacta."},
        )
        assert response.status_code == 201, response.text
        movement = response.json()
        assert movement["quantity"] == 2.375
        assert movement["quantity_exact"] == "2.375"
        assert movement["unit_code"] == "kg"
        assert movement["source_snapshot_id"] == source_snapshot_id

        history = client.get(
            f"/api/v1/inventory/movements/{movement['id']}/events",
        )
        assert history.status_code == 200, history.text
        evidence = history.json()[0]["evidence"]
        assert evidence["quantity_exact"] == "2.375"
        assert evidence["unit_code"] == "kg"

        with TestingSession() as db:
            persisted = db.get(models.InventoryMovement, movement["id"])
            assert persisted is not None
            assert str(persisted.quantity) == "2.375"
            assert persisted.unit_code == "kg"


def test_inventory_reconciliation_rejects_precision_beyond_numeric_scale(monkeypatch):
    with TestClient(app) as client:
        store_id, _, task_id, _ = _completed_replenishment(
            client, unit="kg", actual_quantity=1.2345,
        )
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

        response = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Precisão acima da escala suportada."},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "MOVEMENT_QUANTITY_PRECISION_UNSUPPORTED"
        with TestingSession() as db:
            assert db.query(models.InventoryMovement).filter_by(task_id=task_id).count() == 0
            assert db.query(models.InventorySnapshot).filter_by(
                source="MANUAL",
                external_reference=f"TASK-RECONCILIATION-{task_id}",
            ).count() == 0


def test_product_base_unit_rejects_blank_values():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/products",
            json={"sku": "INVALID-UNIT", "name": "Invalid unit product", "unit": "   "},
        )
        assert response.status_code == 422


def test_inventory_movement_event_is_recorded_atomically_and_readable(monkeypatch):
    with TestClient(app) as client:
        store_id, _, task_id, _ = _completed_replenishment(client)
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
        response = client.post(f"/api/v1/tasks/{task_id}/reconcile-inventory", json={"reason": "Reposição física confirmada e auditada."})
        assert response.status_code == 201, response.text
        movement = response.json()
        history = client.get(f"/api/v1/inventory/movements/{movement['id']}/events")
        assert history.status_code == 200, history.text
        assert len(history.json()) == 1
        event = history.json()[0]
        assert event["movement_id"] == movement["id"]
        assert event["operation_id"] == movement["operation_id"]
        assert event["store_id"] == store_id
        assert event["event_type"] == "MOVEMENT_RECORDED"
        assert event["actor_user_id"] == actor.id
        assert event["reason"] == movement["reason"]
        assert movement["unit_code"] == "un"
        assert movement["quantity_exact"] == "4.000"
        assert event["evidence"]["source_location_code"] == "BACKROOM-A"
        assert event["evidence"]["unit_code"] == "un"
        assert event["evidence"]["quantity_exact"] == "4.000"
        assert event["evidence"]["destination_shelf_id"] == movement["destination_shelf_id"]
        with TestingSession() as db:
            assert db.query(models.InventoryMovement).count() == 1
            assert db.query(models.InventoryMovementEvent).count() == 1


def test_inventory_movement_event_history_hides_foreign_movements_and_rejects_employees(monkeypatch):
    with TestClient(app) as client:
        store_a, _, task_a, _ = _completed_replenishment(client)
        store_b, _, task_b, _ = _completed_replenishment(client)
        actor_a, actor_b = _supervisor_actor(store_a), _supervisor_actor(store_b)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor_a)
        own = client.post(f"/api/v1/tasks/{task_a}/reconcile-inventory", json={"reason": "Movimento loja A."})
        assert own.status_code == 201, own.text
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor_b)
        foreign_movement = client.post(f"/api/v1/tasks/{task_b}/reconcile-inventory", json={"reason": "Movimento loja B."})
        assert foreign_movement.status_code == 201, foreign_movement.text
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor_a)
        foreign = client.get(f"/api/v1/inventory/movements/{foreign_movement.json()['id']}/events")
        missing = client.get("/api/v1/inventory/movements/2147483000/events")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
        employee = _supervisor_actor(store_a, role="EMPLOYEE")
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: employee)
        denied = client.get(f"/api/v1/inventory/movements/{own.json()['id']}/events")
        assert denied.status_code == 403


def test_movement_event_insert_failure_rolls_back_movement_snapshot_and_task_audit(monkeypatch):
    with TestClient(app) as client:
        store_id, _, task_id, _ = _completed_replenishment(client)
        actor = _supervisor_actor(store_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
        with TestingSession() as db:
            db.connection().exec_driver_sql("""
                CREATE TRIGGER fail_inventory_movement_event_insert
                BEFORE INSERT ON inventory_movement_events
                BEGIN SELECT RAISE(ABORT, 'forced movement event failure'); END
            """)
        response = client.post(f"/api/v1/tasks/{task_id}/reconcile-inventory", json={"reason": "Teste de atomicidade do ledger."})
        assert response.status_code == 409, response.text
        with TestingSession() as db:
            assert db.query(models.InventoryMovement).count() == 0
            assert db.query(models.InventoryMovementEvent).count() == 0
            assert db.query(models.InventorySnapshot).count() == 1
            assert db.query(models.ReplenishmentTaskEvent).filter_by(task_id=task_id, event_type="INVENTORY_RECONCILED").count() == 0

