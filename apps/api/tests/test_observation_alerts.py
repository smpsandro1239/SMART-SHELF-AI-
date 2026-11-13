import os
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import models
from app.main import app
import app.main as main_module


ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=ENGINE)


def override_get_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


def _setup_alert_fixture():
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    db = Session()
    store = models.Store(code="ALERT-STORE", name="Loja alertas")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Bebidas")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="ALERT-SHELF")
    db.add(shelf)
    product = models.Product(sku="ALERT-SKU", name="Produto alerta")
    db.add(product)
    user = models.User(
        email="supervisor-alert@example.test",
        store_id=store.id,
        full_name="Supervisor Alertas",
        password_hash="test-hash",
        role="SUPERVISOR",
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(models.ShelfProduct(shelf_id=shelf.id, product_id=product.id))
    now = datetime.now(timezone.utc)
    for seconds_ago in (60, 40, 20):
        db.add(models.Observation(
            shelf_id=shelf.id,
            product_id=product.id,
            source="simulation",
            status="LOW_STOCK",
            confidence=0.95,
            observed_at=now - timedelta(seconds=seconds_ago),
        ))
    db.commit()
    result = SimpleNamespace(id=user.id, role=user.role, store_id=store.id)
    ids = (store.id, shelf.id, product.id)
    db.close()
    return ids, result


def test_observation_alert_is_idempotent_and_human_resolvable(monkeypatch):
    (store_id, shelf_id, product_id), actor = _setup_alert_fixture()
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
    with TestClient(app) as client:
        params = {
            "product_id": product_id,
            "minimum_confirmations": 3,
            "minimum_interval_seconds": 10,
            "minimum_confidence": 0.6,
        }
        first = client.post(f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate", params=params)
        second = client.post(f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate", params=params)
        assert first.status_code == second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["status"] == "OPEN"

        listed = client.get("/api/v1/observation-alerts", params={"status": "OPEN"})
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        missing_reason = client.patch(
            f"/api/v1/observation-alerts/{first.json()['id']}",
            json={"status": "RESOLVED", "reason": "   "},
        )
        assert missing_reason.status_code == 422

        acknowledged = client.patch(
            f"/api/v1/observation-alerts/{first.json()['id']}",
            json={"status": "ACKNOWLEDGED"},
        )
        assert acknowledged.status_code == 200
        assert acknowledged.json()["status"] == "ACKNOWLEDGED"

        resolved = client.patch(
            f"/api/v1/observation-alerts/{first.json()['id']}",
            json={"status": "RESOLVED", "reason": "Prateleira verificada e reposta"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "RESOLVED"
        assert resolved.json()["resolution_reason"] == "Prateleira verificada e reposta"

        events = client.get(f"/api/v1/observation-alerts/{first.json()['id']}/events")
        assert events.status_code == 200
        assert [event["event_type"] for event in events.json()] == [
            "CREATED", "ACKNOWLEDGED", "RESOLVED"
        ]

        reopened = client.post(f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate", params=params)
        assert reopened.status_code == 200
        assert reopened.json()["id"] != first.json()["id"]
        assert reopened.json()["status"] == "OPEN"


def test_observation_alerts_are_store_scoped(monkeypatch):
    (store_id, shelf_id, product_id), actor = _setup_alert_fixture()
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: SimpleNamespace(
        id=actor.id, role="SUPERVISOR", store_id=store_id + 999
    ))
    with TestClient(app) as client:
        response = client.get("/api/v1/observation-alerts")
        assert response.status_code == 200
        assert response.json() == []
        evaluate = client.post(
            f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate",
            params={"product_id": product_id, "minimum_confirmations": 3},
        )
        assert evaluate.status_code == 403
