import os

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
