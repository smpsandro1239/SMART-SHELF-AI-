import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

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


def setup_module():
    Base.metadata.create_all(bind=TEST_ENGINE)
    app.dependency_overrides[get_db] = override_get_db


def teardown_module():
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=TEST_ENGINE)


def test_product_catalog_and_shelf_assignment():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "CAT-01", "name": "Loja catálogo"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Bebidas"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "BEB-02"})
        product = client.post(
            "/api/v1/products",
            json={"sku": "5601234567890", "name": "Água 1,5 L", "brand": "Marca Exemplo", "unit": "un"},
        )
        assert product.status_code == 201
        assignment = client.post(
            "/api/v1/shelf-products",
            json={
                "shelf_id": shelf.json()["id"],
                "product_id": product.json()["id"],
                "target_quantity": 12,
                "min_display_quantity": 4,
                "position": "nível 2",
            },
        )
        assert assignment.status_code == 201
        assert assignment.json()["target_quantity"] == 12
        listed = client.get("/api/v1/shelf-products", params={"shelf_id": shelf.json()["id"]})
        assert listed.status_code == 200
        assert len(listed.json()) == 1


def test_duplicate_sku_and_duplicate_assignment_are_rejected():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "CAT-02", "name": "Loja teste"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Laticínios"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "LAT-01"})
        payload = {"sku": "SKU-001", "name": "Leite"}
        product = client.post("/api/v1/products", json=payload)
        duplicate_product = client.post("/api/v1/products", json=payload)
        assert product.status_code == 201
        assert duplicate_product.status_code == 409

        assignment_payload = {
            "shelf_id": shelf.json()["id"],
            "product_id": product.json()["id"],
            "target_quantity": 8,
        }
        first = client.post("/api/v1/shelf-products", json=assignment_payload)
        duplicate = client.post("/api/v1/shelf-products", json=assignment_payload)
        assert first.status_code == 201
        assert duplicate.status_code == 409


def test_invalid_target_quantity_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/shelf-products",
            json={"shelf_id": 1, "product_id": 1, "target_quantity": 0},
        )
        assert response.status_code == 422
