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
import app.main as main_module

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


def test_product_catalog_and_shelf_assignment():
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


def test_inactive_product_cannot_be_assigned_to_shelf():
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "CAT-INACTIVE", "name": "Loja teste"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Mercearia"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "MER-INACTIVE"})
        product = client.post(
            "/api/v1/products",
            json={"sku": "SKU-INACTIVE", "name": "Produto inactivo", "is_active": False},
        )
        assert product.status_code == 201

        assignment = client.post(
            "/api/v1/shelf-products",
            json={
                "shelf_id": shelf.json()["id"],
                "product_id": product.json()["id"],
                "target_quantity": 5,
            },
        )

        assert assignment.status_code == 409
        assert assignment.json()["detail"] == "Inactive products cannot be assigned to a shelf"
        assert client.get(
            "/api/v1/shelf-products",
            params={"shelf_id": shelf.json()["id"]},
        ).json() == []


def test_invalid_target_quantity_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/shelf-products",
            json={"shelf_id": 1, "product_id": 1, "target_quantity": 0},
        )
        assert response.status_code == 422



def test_shelf_product_listing_is_scoped_to_supervisor_store(monkeypatch):
    from types import SimpleNamespace

    with TestClient(app) as client:
        stores = []
        shelves = []
        product = client.post(
            "/api/v1/products",
            json={"sku": "SHARED-CATALOG-01", "name": "Produto partilhado"},
        )
        assert product.status_code == 201

        for index in (1, 2):
            store = client.post(
                "/api/v1/stores",
                json={"code": f"SCOPE-CAT-{index}", "name": f"Loja {index}"},
            )
            zone = client.post(
                "/api/v1/zones",
                json={"store_id": store.json()["id"], "name": "Mercearia"},
            )
            shelf = client.post(
                "/api/v1/shelves",
                json={"zone_id": zone.json()["id"], "code": f"MER-{index}"},
            )
            assignment = client.post(
                "/api/v1/shelf-products",
                json={
                    "shelf_id": shelf.json()["id"],
                    "product_id": product.json()["id"],
                    "target_quantity": 10,
                },
            )
            assert assignment.status_code == 201
            stores.append(store.json()["id"])
            shelves.append(shelf.json()["id"])

        supervisor = SimpleNamespace(role="SUPERVISOR", store_id=stores[0])
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: supervisor)

        own_store_rows = client.get("/api/v1/shelf-products")
        assert own_store_rows.status_code == 200
        assert [row["shelf_id"] for row in own_store_rows.json()] == [shelves[0]]

        forged_foreign_filter = client.get(
            "/api/v1/shelf-products",
            params={"shelf_id": shelves[1]},
        )
        assert forged_foreign_filter.status_code == 200
        assert forged_foreign_filter.json() == []

        admin = SimpleNamespace(role="ADMIN", store_id=None)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: admin)
        admin_rows = client.get("/api/v1/shelf-products")
        assert admin_rows.status_code == 200
        assert {row["shelf_id"] for row in admin_rows.json()} == set(shelves)

def test_shelf_product_assignment_is_scoped_to_supervisor_store(monkeypatch):
    from types import SimpleNamespace

    with TestClient(app) as client:
        product = client.post(
            "/api/v1/products",
            json={"sku": "SCOPE-ASSIGN-01", "name": "Produto de teste"},
        )
        assert product.status_code == 201

        stores = []
        shelves = []
        for index in (1, 2):
            store = client.post(
                "/api/v1/stores",
                json={"code": f"ASSIGN-SCOPE-{index}", "name": f"Loja {index}"},
            )
            zone = client.post(
                "/api/v1/zones",
                json={"store_id": store.json()["id"], "name": "Mercearia"},
            )
            shelf = client.post(
                "/api/v1/shelves",
                json={"zone_id": zone.json()["id"], "code": f"ASSIGN-{index}"},
            )
            stores.append(store.json()["id"])
            shelves.append(shelf.json()["id"])

        supervisor = SimpleNamespace(role="SUPERVISOR", store_id=stores[0])
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: supervisor)

        own_assignment = client.post(
            "/api/v1/shelf-products",
            json={
                "shelf_id": shelves[0],
                "product_id": product.json()["id"],
                "target_quantity": 10,
            },
        )
        assert own_assignment.status_code == 201

        foreign_assignment = client.post(
            "/api/v1/shelf-products",
            json={
                "shelf_id": shelves[1],
                "product_id": product.json()["id"],
                "target_quantity": 10,
            },
        )
        assert foreign_assignment.status_code == 404

