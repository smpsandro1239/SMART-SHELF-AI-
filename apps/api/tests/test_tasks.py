import os
import json

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError

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

        completed = client.patch(f"/api/v1/tasks/{task_id}/status", json={
            "status": "COMPLETED", "actual_quantity": 8,
        })
        assert completed.status_code == 200
        assert completed.json()["completed_at"] is not None
        assert completed.json()["actual_quantity"] == 8

        events = client.get(f"/api/v1/tasks/{task_id}/events")
        assert events.status_code == 200
        assert [event["event_type"] for event in events.json()] == ["CREATED", "STATUS_CHANGED", "STATUS_CHANGED", "STATUS_CHANGED"]
        assert events.json()[0]["from_status"] is None
        assert events.json()[0]["to_status"] == "PENDING"
        assert [event["to_status"] for event in events.json()[1:]] == ["ASSIGNED", "IN_PROGRESS", "COMPLETED"]
        assert events.json()[-1]["actual_quantity"] == 8

        # A terminal task releases the active-task slot for a future replenishment.
        next_task = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
            "requested_quantity": 2,
        })
        assert next_task.status_code == 201



def test_database_unique_index_blocks_duplicate_active_tasks():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        created = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        })
        assert created.status_code == 201

        duplicate_response = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        })
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["detail"]["code"] == "ACTIVE_TASK_EXISTS"

        db = TestingSession()
        try:
            duplicate = models.ReplenishmentTask(
                store_id=store_id,
                shelf_id=shelf_id,
                product_id=product_id,
                status="PENDING",
            )
            db.add(duplicate)
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
        finally:
            db.close()

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


def test_task_can_be_created_from_verified_recommendation_only_once():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "LOW_STOCK", "confidence": 0.94,
        })
        assert observation.status_code == 201
        inventory = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 15, "reserved_quantity": 3, "source": "ERP",
        })
        assert inventory.status_code == 201

        payload = {
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
            "priority": "HIGH", "requested_quantity": 6,
        }
        created = client.post("/api/v1/tasks/from-recommendation", json=payload)
        assert created.status_code == 201
        assert created.json()["status"] == "PENDING"
        audit = client.get(f"/api/v1/tasks/{created.json()['id']}/events")
        assert audit.status_code == 200
        assert len(audit.json()) == 1
        assert audit.json()[0]["event_type"] == "CREATED"
        assert audit.json()[0]["to_status"] == "PENDING"

        duplicate = client.post("/api/v1/tasks/from-recommendation", json=payload)
        assert duplicate.status_code == 409


def test_task_from_recommendation_is_rejected_without_backroom_stock():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "EMPTY", "confidence": 0.99,
        })
        client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 0, "reserved_quantity": 0, "source": "WMS",
        })

        response = client.post("/api/v1/tasks/from-recommendation", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        })
        assert response.status_code == 409



def test_task_can_be_assigned_to_active_employee_from_same_store():
    from app.security import hash_password

    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        with TestingSession() as db:
            employee = models.User(
                email="employee@example.com",
                full_name="Funcionário de teste",
                password_hash=hash_password("Test-password-12345"),
                role="EMPLOYEE",
                store_id=store_id,
                is_active=True,
            )
            db.add(employee)
            db.commit()
            db.refresh(employee)
            employee_id = employee.id

        created = client.post("/api/v1/tasks", json={
            "store_id": store_id,
            "shelf_id": shelf_id,
            "product_id": product_id,
            "assigned_user_id": employee_id,
        })
        assert created.status_code == 201
        assert created.json()["assigned_user_id"] == employee_id
        assert created.json()["assigned_to"] == "Funcionário de teste"
        assert created.json()["status"] == "ASSIGNED"


def test_task_rejects_employee_from_another_store():
    from app.security import hash_password

    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        with TestingSession() as db:
            other_store = models.Store(code="OTHER-STORE", name="Outra loja")
            db.add(other_store)
            db.commit()
            db.refresh(other_store)
            employee = models.User(
                email="other@example.com",
                full_name="Funcionário externo",
                password_hash=hash_password("Test-password-12345"),
                role="EMPLOYEE",
                store_id=other_store.id,
                is_active=True,
            )
            db.add(employee)
            db.commit()
            db.refresh(employee)
            employee_id = employee.id

        response = client.post("/api/v1/tasks", json={
            "store_id": store_id,
            "shelf_id": shelf_id,
            "product_id": product_id,
            "assigned_user_id": employee_id,
        })
        assert response.status_code == 422


def test_task_from_measured_recommendation_uses_suggested_refill_quantity():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation", "status": "LOW_STOCK",
            "confidence": 0.95, "observed_quantity": 1,
        })
        assert observation.status_code == 201
        inventory = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 8, "reserved_quantity": 0, "source": "WMS",
        })
        assert inventory.status_code == 201

        created = client.post("/api/v1/tasks/from-recommendation", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        })
        assert created.status_code == 201
        assert created.json()["requested_quantity"] == 8


@pytest.mark.parametrize("invalid_quantity", [float("nan"), float("inf"), float("-inf")])
def test_task_rejects_non_finite_requested_quantities(invalid_quantity):
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        response = client.post(
            "/api/v1/tasks",
            content=json.dumps({
                "store_id": store_id,
                "shelf_id": shelf_id,
                "product_id": product_id,
                "requested_quantity": invalid_quantity,
            }),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(error["type"] == "finite_number" for error in errors)
        assert all(
            not isinstance(error.get("input"), float)
            or __import__("math").isfinite(error["input"])
            for error in errors
        )


def test_task_completion_requires_actual_quantity_and_reason_for_partial_refill():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        created = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
            "requested_quantity": 8,
        })
        task_id = created.json()["id"]
        client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "ASSIGNED", "assigned_to": "ana"})
        client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "IN_PROGRESS"})

        missing_quantity = client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "COMPLETED"})
        assert missing_quantity.status_code == 422
        assert missing_quantity.json()["detail"]["code"] == "ACTUAL_QUANTITY_REQUIRED"

        missing_reason = client.patch(f"/api/v1/tasks/{task_id}/status", json={
            "status": "COMPLETED", "actual_quantity": 5,
        })
        assert missing_reason.status_code == 422
        assert missing_reason.json()["detail"]["code"] == "PARTIAL_COMPLETION_REASON_REQUIRED"

        completed = client.patch(f"/api/v1/tasks/{task_id}/status", json={
            "status": "COMPLETED", "actual_quantity": 5,
            "exception_reason": "Stock insuficiente na retaguarda",
        })
        assert completed.status_code == 200
        assert completed.json()["actual_quantity"] == 5
        assert completed.json()["exception_reason"] == "Stock insuficiente na retaguarda"
        events = client.get(f"/api/v1/tasks/{task_id}/events")
        assert events.status_code == 200
        assert events.json()[-1]["reason"] == "Stock insuficiente na retaguarda"


def test_task_cancellation_requires_reason_and_is_audited():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        created = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        })
        task_id = created.json()["id"]

        missing_reason = client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "CANCELLED"})
        assert missing_reason.status_code == 422
        assert missing_reason.json()["detail"]["code"] == "CANCELLATION_REASON_REQUIRED"

        cancelled = client.patch(f"/api/v1/tasks/{task_id}/status", json={
            "status": "CANCELLED", "exception_reason": "Produto descontinuado",
        })
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "CANCELLED"
        events = client.get(f"/api/v1/tasks/{task_id}/events")
        assert events.status_code == 200
        assert events.json()[-1]["event_type"] == "STATUS_CHANGED"
        assert events.json()[-1]["reason"] == "Produto descontinuado"
