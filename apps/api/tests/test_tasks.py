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


def create_task_context(client):
    store = client.post("/api/v1/stores", json={"code": "TASK-01", "name": "Loja tarefas"})
    store_id = store.json()["id"]
    zone = client.post("/api/v1/zones", json={"store_id": store_id, "name": "Bebidas"})
    shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "BEB-01"})
    product = client.post("/api/v1/products", json={"sku": "TASK-SKU-01", "name": "Água 1,5 L"})
    client.post("/api/v1/shelf-products", json={
        "shelf_id": shelf.json()["id"], "product_id": product.json()["id"],
        "target_quantity": 12, "min_display_quantity": 3,
    })
    return store_id, shelf.json()["id"], product.json()["id"]


def test_task_lifecycle_pending_assignment_start_and_completion():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        created = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
            "priority": "HIGH", "requested_quantity": 8,
        })
        assert created.status_code == 201
        task = created.json()
        assert task["status"] == "PENDING"
        task_id = task["id"]

        assigned = client.patch(f"/api/v1/tasks/{task_id}/status", json={
            "status": "ASSIGNED", "assigned_to": "funcionario-01",
        })
        assert assigned.status_code == 200
        assert assigned.json()["assigned_to"] == "funcionario-01"

        started = client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "IN_PROGRESS"})
        assert started.status_code == 200
        assert started.json()["started_at"] is not None

        completed = client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "COMPLETED"})
        assert completed.status_code == 200
        assert completed.json()["completed_at"] is not None


def test_task_rejects_invalid_transition_and_unlinked_product():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        bad_product = client.post("/api/v1/products", json={"sku": "OTHER", "name": "Outro"})
        invalid = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": bad_product.json()["id"],
        })
        assert invalid.status_code == 409

        created = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        })
        task_id = created.json()["id"]
        cannot_complete_directly = client.patch(
            f"/api/v1/tasks/{task_id}/status", json={"status": "COMPLETED"},
        )
        assert cannot_complete_directly.status_code == 409


def test_task_list_filters_by_status_and_assignee():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
            "assigned_to": "ana",
        })
        pending = client.get("/api/v1/tasks", params={"store_id": store_id, "status": "ASSIGNED"})
        assert pending.status_code == 200
        assert len(pending.json()) == 1
        by_assignee = client.get("/api/v1/tasks", params={"assigned_to": "ana"})
        assert len(by_assignee.json()) == 1
