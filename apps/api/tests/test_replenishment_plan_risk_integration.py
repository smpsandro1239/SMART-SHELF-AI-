import os
from datetime import date, datetime, timedelta, timezone

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import models  # noqa: F401
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


def _create_candidate(client, store_id, code, sku, name, stock, zone_id=None):
    if zone_id is None:
        zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Mercearia",
        }).json()
        zone_id = zone["id"]
    shelf = client.post("/api/v1/shelves", json={
        "zone_id": zone_id, "code": code,
    }).json()
    product = client.post("/api/v1/products", json={
        "sku": sku, "name": name,
    }).json()
    linked = client.post("/api/v1/shelf-products", json={
        "shelf_id": shelf["id"], "product_id": product["id"],
        "target_quantity": 12, "min_display_quantity": 3,
    })
    assert linked.status_code == 201
    observation = client.post("/api/v1/observations", json={
        "shelf_id": shelf["id"], "status": "LOW_STOCK",
        "confidence": 0.95, "source": "simulation",
    })
    assert observation.status_code == 201
    inventory = client.post("/api/v1/inventory/snapshots", json={
        "store_id": store_id, "product_id": product["id"],
        "on_hand_quantity": stock, "reserved_quantity": 0,
        "source": "ERP",
    })
    assert inventory.status_code == 201
    return product["id"]


def test_replenishment_plan_uses_fresh_inventory_and_complete_sales_history_for_priority():
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={
            "code": "RISK-PLAN-01", "name": "Loja risco reposição",
        })
        assert store.status_code == 201
        store_id = store.json()["id"]

        zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Mercearia",
        }).json()
        critical_product_id = _create_candidate(
            client, store_id, "MER-CRIT", "RISK-CRIT", "Produto crítico", 20,
            zone_id=zone["id"],
        )
        medium_product_id = _create_candidate(
            client, store_id, "MER-MED", "RISK-MED", "Produto médio", 50,
            zone_id=zone["id"],
        )

        today = date.today()
        with TestingSession() as db:
            for product_id in (critical_product_id, medium_product_id):
                for offset in range(28):
                    db.add(models.DailySalesRecord(
                        store_id=store_id,
                        product_id=product_id,
                        sales_date=today - timedelta(days=offset),
                        quantity=10,
                        source="POS",
                        external_reference=f"RISK-{product_id}-{offset}",
                    ))
            db.commit()

        response = client.get("/api/v1/replenishment/plan", params={
            "store_id": store_id,
            "include_stockout_risk": "true",
            "risk_source": "POS",
            "risk_days": 28,
            "risk_lead_time_days": 3,
        })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["risk_assessment"]["enabled"] is True
        assert payload["automatic_stock_movement_allowed"] is False

        tasks = [
            item
            for group in payload["groups"]
            for item in group["tasks"]
        ]
        assert [item["product_id"] for item in tasks] == [
            critical_product_id, medium_product_id,
        ]
        assert [item["stockout_risk_level"] for item in tasks] == [
            "CRITICAL", "MEDIUM",
        ]
        assert all(item["task_creation_allowed"] is False for item in tasks)


def test_replenishment_plan_keeps_unknown_risk_when_sales_history_is_incomplete():
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={
            "code": "RISK-PLAN-02", "name": "Loja histórico incompleto",
        })
        store_id = store.json()["id"]
        product_id = _create_candidate(
            client, store_id, "MER-UNK", "RISK-UNK", "Produto sem histórico", 100,
        )
        with TestingSession() as db:
            for offset in range(27):
                db.add(models.DailySalesRecord(
                    store_id=store_id,
                    product_id=product_id,
                    sales_date=date.today() - timedelta(days=offset),
                    quantity=0,
                    source="POS",
                    external_reference=f"RISK-UNKNOWN-{offset}",
                ))
            db.commit()

        response = client.get("/api/v1/replenishment/plan", params={
            "store_id": store_id,
            "include_stockout_risk": "true",
            "risk_source": "POS",
            "risk_days": 28,
        })
        assert response.status_code == 200, response.text
        item = response.json()["groups"][0]["tasks"][0]
        assert item["stockout_risk_level"] == "UNKNOWN"
        assert item["stockout_risk_basis"] == "INSUFFICIENT_EVIDENCE"
        assert item["stockout_missing_sales_days"] == 1


def test_replenishment_plan_adds_elapsed_effort_estimates_from_completed_history():
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={
            "code": "EFFORT-PLAN-01", "name": "Loja estimativa esforço",
        })
        assert store.status_code == 201
        store_id = store.json()["id"]
        zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Bebidas",
        }).json()
        product_id = _create_candidate(
            client, store_id, "EFFORT-SHELF", "EFFORT-SKU",
            "Produto para estimativa", 20, zone_id=zone["id"],
        )

        with TestingSession() as db:
            shelf = db.query(models.Shelf).filter_by(code="EFFORT-SHELF").one()
            now = datetime.now(timezone.utc)
            for index in range(5):
                started = now - timedelta(days=index + 1)
                db.add(models.ReplenishmentTask(
                    store_id=store_id,
                    shelf_id=shelf.id,
                    product_id=product_id,
                    priority="NORMAL",
                    status="COMPLETED",
                    started_at=started,
                    completed_at=started + timedelta(minutes=10 + index),
                ))
            db.commit()

        response = client.get("/api/v1/replenishment/plan", params={
            "store_id": store_id,
            "include_effort_estimates": "true",
            "effort_history_days": 90,
            "effort_minimum_sample_size": 5,
        })
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["effort_estimation"]["enabled"] is True
        assert payload["effort_estimation"]["historical_valid_samples"] == 5
        assert payload["effort_estimation"]["estimated_candidates"] == 1
        item = payload["groups"][0]["tasks"][0]
        assert item["estimated_elapsed_minutes"] == 12
        assert item["effort_estimate_basis"] == "ZONE_AND_PRIORITY_HISTORY"
        assert item["effort_metric"] == "ELAPSED_TIME_NOT_ACTIVE_LABOUR"


def test_replenishment_plan_validates_effort_estimate_parameters():
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={
            "code": "EFFORT-PLAN-02", "name": "Loja parâmetros esforço",
        })
        response = client.get("/api/v1/replenishment/plan", params={
            "store_id": store.json()["id"],
            "include_effort_estimates": "true",
            "effort_minimum_sample_size": 1,
        })
        assert response.status_code == 422
