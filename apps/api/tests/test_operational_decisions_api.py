import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import models
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


def create_context(client):
    store = client.post("/api/v1/stores", json={"code": "DEC-01", "name": "Loja decisões"})
    store_id = store.json()["id"]
    zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Mercearia"})
    shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "MER-01"})
    product = client.post("/api/v1/products", json={"sku": "DEC-SKU-01", "name": "Arroz"})
    client.post("/api/v1/shelf-products", json={
        "shelf_id": shelf.json()["id"], "product_id": product.json()["id"],
        "target_quantity": 12, "min_display_quantity": 3,
    })
    return store_id, shelf.json()["id"], product.json()["id"]


def test_operational_decisions_use_latest_shelf_evidence_and_do_not_create_tasks():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        created = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "EMPTY", "confidence": 0.96,
        })
        assert created.status_code == 201

        response = client.get("/api/v1/operational-decisions", params={"store_id": store_id})
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        decision = body["decisions"][0]
        assert decision["product_id"] == product_id
        assert decision["decision"]["status"] == "ACTION_RECOMMENDED"
        assert decision["decision"]["priority"] == "HIGH"
        assert decision["decision"]["suggested_replenishment_quantity"] is None
        assert body["side_effects"] == {"tasks_created": 0, "inventory_changed": False}

        tasks = client.get("/api/v1/tasks", params={"store_id": store_id})
        assert tasks.status_code == 200
        assert tasks.json() == []


def test_operational_decisions_report_insufficient_evidence_without_fabricating_stock():
    with TestClient(app) as client:
        store_id, _, _ = create_context(client)
        response = client.get("/api/v1/operational-decisions", params={"store_id": store_id})
        assert response.status_code == 200
        result = response.json()["decisions"][0]["decision"]
        assert result["status"] == "INSUFFICIENT_EVIDENCE"
        assert result["suggested_replenishment_quantity"] is None
        assert result["automatic_stock_movement_allowed"] is False


def test_operational_decisions_suppress_duplicate_work_for_active_task():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "EMPTY", "confidence": 0.99,
        })
        task = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
            "priority": "HIGH",
        })
        assert task.status_code == 201

        response = client.get("/api/v1/operational-decisions", params={"store_id": store_id})
        assert response.status_code == 200
        result = response.json()["decisions"][0]["decision"]
        assert result["status"] == "ALREADY_IN_PROGRESS"
        assert result["suggested_replenishment_quantity"] is None


def test_operational_decisions_filter_by_shelf_and_product():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        response = client.get("/api/v1/operational-decisions", params={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        })
        assert response.status_code == 200
        assert response.json()["count"] == 1
        assert response.json()["decisions"][0]["shelf_id"] == shelf_id


def test_operational_decisions_reject_unknown_store():
    with TestClient(app) as client:
        response = client.get("/api/v1/operational-decisions", params={"store_id": 9999})
        assert response.status_code == 404


def test_operational_decisions_prioritize_high_confidence_empty_shelves():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        second_zone = client.post("/api/v1/zones", json={
            "store_id": store_id, "name": "Bebidas",
        }).json()
        second_shelf = client.post("/api/v1/shelves", json={
            "zone_id": second_zone["id"], "code": "BEB-02",
        }).json()
        second_product = client.post("/api/v1/products", json={
            "sku": "DEC-SKU-02", "name": "Massa",
        }).json()
        client.post("/api/v1/shelf-products", json={
            "shelf_id": second_shelf["id"], "product_id": second_product["id"],
            "target_quantity": 12, "min_display_quantity": 3,
        })
        client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "LOW_STOCK", "confidence": 0.90,
        })
        client.post("/api/v1/observations", json={
            "shelf_id": second_shelf["id"], "source": "simulation",
            "status": "EMPTY", "confidence": 0.99,
        })

        response = client.get("/api/v1/operational-decisions", params={"store_id": store_id})
        assert response.status_code == 200
        body = response.json()
        assert body["decisions"][0]["product_id"] == second_product["id"]
        assert body["decisions"][0]["decision"]["priority"] == "HIGH"
        assert body["priority_counts"]["HIGH"] == 1
        assert body["priority_counts"]["NORMAL"] == 1
