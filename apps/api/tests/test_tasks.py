import os
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

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
from app.security import create_access_token
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
        assert duplicate.json()["detail"]["code"] == "ACTIVE_TASK_EXISTS"


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


def test_task_cancellation_lifecycle_has_exactly_one_event_per_transition():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        created = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        })
        assert created.status_code == 201
        task_id = created.json()["id"]

        assigned = client.patch(f"/api/v1/tasks/{task_id}/status", json={
            "status": "ASSIGNED", "assigned_to": "operador-01",
        })
        assert assigned.status_code == 200
        cancelled = client.patch(f"/api/v1/tasks/{task_id}/status", json={
            "status": "CANCELLED", "exception_reason": "Reposição já não necessária",
        })
        assert cancelled.status_code == 200

        duplicate_cancel = client.patch(f"/api/v1/tasks/{task_id}/status", json={
            "status": "CANCELLED", "exception_reason": "Pedido repetido",
        })
        assert duplicate_cancel.status_code == 409

        events = client.get(f"/api/v1/tasks/{task_id}/events")
        assert events.status_code == 200
        audit = events.json()
        assert [event["event_type"] for event in audit] == [
            "CREATED", "STATUS_CHANGED", "STATUS_CHANGED",
        ]
        assert [(event["from_status"], event["to_status"]) for event in audit] == [
            (None, "PENDING"), ("PENDING", "ASSIGNED"), ("ASSIGNED", "CANCELLED"),
        ]
        assert audit[-1]["reason"] == "Reposição já não necessária"
        assert len({event["id"] for event in audit}) == len(audit)


def test_task_status_and_audit_event_roll_back_together_when_audit_fails(monkeypatch):
    from app import main as main_module

    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        created = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        })
        assert created.status_code == 201
        task_id = created.json()["id"]

        original_record_task_event = main_module._record_task_event

        def fail_audit(db, task, event_type, actor, **kwargs):
            original_record_task_event(db, task, event_type, actor, **kwargs)
            db.flush()
            raise RuntimeError("forced task audit failure after flush")

        monkeypatch.setattr(main_module, "_record_task_event", fail_audit)
        with TestClient(app, raise_server_exceptions=False) as failing_client:
            response = failing_client.patch(
                f"/api/v1/tasks/{task_id}/status",
                json={"status": "CANCELLED", "exception_reason": "Teste de rollback"},
            )
        assert response.status_code == 500

        monkeypatch.undo()
        task_after_failure = client.get("/api/v1/tasks")
        assert task_after_failure.status_code == 200
        task = next(item for item in task_after_failure.json() if item["id"] == task_id)
        assert task["status"] == "PENDING"
        events = client.get(f"/api/v1/tasks/{task_id}/events")
        assert events.status_code == 200
        assert [event["event_type"] for event in events.json()] == ["CREATED"]



def _freshness_reconciliation_context(client, snapshot_age_minutes: int):
    store_id, shelf_id, product_id = create_task_context(client)
    snapshot = client.post("/api/v1/inventory/snapshots", json={
        "store_id": store_id,
        "product_id": product_id,
        "on_hand_quantity": 20,
        "reserved_quantity": 2,
        "source": "WMS",
        "external_reference": f"FRESH-{uuid4().hex[:10]}",
        "captured_at": (datetime.now(timezone.utc) - timedelta(minutes=snapshot_age_minutes)).isoformat(),
    })
    assert snapshot.status_code == 201, snapshot.text
    task = client.post("/api/v1/tasks", json={
        "store_id": store_id, "shelf_id": shelf_id, "product_id": product_id,
        "requested_quantity": 5,
    })
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    assert client.patch(f"/api/v1/tasks/{task_id}/status", json={
        "status": "ASSIGNED", "assigned_to": "operador",
    }).status_code == 200
    assert client.patch(f"/api/v1/tasks/{task_id}/status", json={
        "status": "IN_PROGRESS",
    }).status_code == 200
    completed = client.patch(f"/api/v1/tasks/{task_id}/status", json={
        "status": "COMPLETED",
        "actual_quantity": 4,
        "exception_reason": "Quantidade parcial para testar a política de frescura.",
    })
    assert completed.status_code == 200, completed.text

    db = TestingSession()
    try:
        actor = models.User(
            email=f"freshness-{uuid4().hex}@example.test",
            store_id=store_id,
            full_name="Freshness Supervisor",
            password_hash="test-only-not-used",
            role="SUPERVISOR",
            is_active=True,
        )
        db.add(actor)
        db.commit()
        db.refresh(actor)
        return store_id, task_id, actor
    finally:
        db.close()


def test_reconciliation_uses_configured_freshness_for_store_and_source(monkeypatch):
    with TestClient(app) as client:
        store_id, task_id, actor = _freshness_reconciliation_context(client, 300)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)

        configured = client.post("/api/v1/inventory/freshness-policies", json={
            "store_id": store_id, "source": "WMS", "max_age_minutes": 360,
        })
        assert configured.status_code == 200, configured.text
        assert configured.json()["max_age_minutes"] == 360

        response = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Política WMS específica da loja"},
        )
        assert response.status_code == 201, response.text

        policies = client.get(
            "/api/v1/inventory/freshness-policies",
            params={"store_id": store_id},
        )
        assert policies.status_code == 200
        assert [(item["source"], item["max_age_minutes"]) for item in policies.json()] == [("WMS", 360)]


def test_reconciliation_rejects_snapshot_outside_configured_source_window(monkeypatch):
    with TestClient(app) as client:
        store_id, task_id, actor = _freshness_reconciliation_context(client, 180)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)

        configured = client.post("/api/v1/inventory/freshness-policies", json={
            "store_id": store_id, "source": "WMS", "max_age_minutes": 120,
        })
        assert configured.status_code == 200, configured.text

        response = client.post(
            f"/api/v1/tasks/{task_id}/reconcile-inventory",
            json={"reason": "Snapshot fora da janela WMS"},
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "INVENTORY_SNAPSHOT_STALE"
        assert detail["source"] == "WMS"
        assert detail["max_age_minutes"] == 120


def test_inventory_freshness_policy_rejects_out_of_range_values(monkeypatch):
    with TestClient(app) as client:
        store_id, _, actor = _freshness_reconciliation_context(client, 10)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
        response = client.post("/api/v1/inventory/freshness-policies", json={
            "store_id": store_id, "source": "WMS", "max_age_minutes": 0,
        })
        assert response.status_code == 422



def test_inventory_freshness_policy_endpoints_enforce_role_and_store_scope(monkeypatch):
    with TestClient(app) as client:
        store_id, _, actor = _freshness_reconciliation_context(client, 10)
        other_store = client.post(
            "/api/v1/stores",
            json={"code": "TASK-OTHER", "name": "Outra loja"},
        )
        assert other_store.status_code == 201, other_store.text
        other_store_id = other_store.json()["id"]

        employee = models.User(
            email=f"freshness-employee-{uuid4().hex}@example.test",
            store_id=store_id,
            full_name="Freshness Employee",
            password_hash="test-only-not-used",
            role="EMPLOYEE",
            is_active=True,
        )
        db = TestingSession()
        try:
            db.add(employee)
            db.commit()
            db.refresh(employee)
        finally:
            db.close()

        monkeypatch.setattr(main_module, "_request_user", lambda db, request: employee)
        assert client.get(
            "/api/v1/inventory/freshness-policies",
            params={"store_id": store_id},
        ).status_code == 403
        assert client.post("/api/v1/inventory/freshness-policies", json={
            "store_id": store_id, "source": "WMS", "max_age_minutes": 300,
        }).status_code == 403

        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
        assert client.get(
            "/api/v1/inventory/freshness-policies",
            params={"store_id": other_store_id},
        ).status_code == 403
        assert client.post("/api/v1/inventory/freshness-policies", json={
            "store_id": other_store_id, "source": "WMS", "max_age_minutes": 300,
        }).status_code == 403


def test_inventory_freshness_policy_upsert_updates_existing_row(monkeypatch):
    with TestClient(app) as client:
        store_id, _, actor = _freshness_reconciliation_context(client, 10)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)

        first = client.post("/api/v1/inventory/freshness-policies", json={
            "store_id": store_id, "source": "WMS", "max_age_minutes": 300,
        })
        second = client.post("/api/v1/inventory/freshness-policies", json={
            "store_id": store_id, "source": "WMS", "max_age_minutes": 420,
        })
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["max_age_minutes"] == 420
        listed = client.get(
            "/api/v1/inventory/freshness-policies",
            params={"store_id": store_id},
        )
        assert len(listed.json()) == 1
        assert listed.json()[0]["max_age_minutes"] == 420



def test_task_event_and_transition_endpoints_reject_cross_store_access(monkeypatch):
    with TestClient(app) as client:
        own_store_id, own_shelf_id, own_product_id = create_task_context(client)
        foreign_store = client.post("/api/v1/stores", json={
            "code": "TASK-FOREIGN", "name": "Loja externa",
        })
        assert foreign_store.status_code == 201
        foreign_store_id = foreign_store.json()["id"]
        foreign_zone = client.post("/api/v1/zones", json={
            "store_id": foreign_store_id, "name": "Zona externa",
        })
        foreign_shelf = client.post("/api/v1/shelves", json={
            "zone_id": foreign_zone.json()["id"], "code": "EXT-01",
        })
        foreign_product = client.post("/api/v1/products", json={
            "sku": "TASK-FOREIGN-SKU", "name": "Produto externo",
        })
        foreign_link = client.post("/api/v1/shelf-products", json={
            "shelf_id": foreign_shelf.json()["id"],
            "product_id": foreign_product.json()["id"],
            "target_quantity": 10,
            "min_display_quantity": 2,
        })
        assert foreign_link.status_code == 201
        foreign_task = client.post("/api/v1/tasks", json={
            "store_id": foreign_store_id,
            "shelf_id": foreign_shelf.json()["id"],
            "product_id": foreign_product.json()["id"],
        })
        own_task = client.post("/api/v1/tasks", json={
            "store_id": own_store_id,
            "shelf_id": own_shelf_id,
            "product_id": own_product_id,
        })
        assert foreign_task.status_code == 201
        assert own_task.status_code == 201

        with TestingSession() as db:
            actor = models.User(
                email="scope-supervisor@example.test",
                full_name="Supervisor da loja própria",
                password_hash="test-only-not-used",
                role="SUPERVISOR",
                store_id=own_store_id,
                is_active=True,
            )
            db.add(actor)
            db.commit()
            db.refresh(actor)
            actor_id = actor.id

        with TestingSession() as db:
            actor = db.get(models.User, actor_id)
            monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

            own_events = client.get(f"/api/v1/tasks/{own_task.json()['id']}/events")
            assert own_events.status_code == 200
            assert len(own_events.json()) == 1

            foreign_events = client.get(f"/api/v1/tasks/{foreign_task.json()['id']}/events")
            missing_events = client.get("/api/v1/tasks/2147483000/events")
            assert foreign_events.status_code == missing_events.status_code == 404
            assert foreign_events.json() == missing_events.json()

            # ADMIN retains global visibility after the supervisor lookup is
            # tenant-scoped directly in SQL.
            actor.role = "ADMIN"
            admin_foreign_events = client.get(
                f"/api/v1/tasks/{foreign_task.json()['id']}/events"
            )
            assert admin_foreign_events.status_code == 200
            assert len(admin_foreign_events.json()) == 1
            actor.role = "SUPERVISOR"

            foreign_task_id = foreign_task.json()["id"]
            before_foreign_state = db.query(models.ReplenishmentTask).filter_by(
                id=foreign_task_id
            ).one().status
            before_foreign_event_count = db.query(models.ReplenishmentTaskEvent).filter_by(
                task_id=foreign_task_id
            ).count()

            foreign_transition = client.patch(
                f"/api/v1/tasks/{foreign_task.json()['id']}/status",
                json={"status": "CANCELLED", "exception_reason": "Tentativa cross-store"},
            )
            missing_transition = client.patch(
                "/api/v1/tasks/2147483000/status",
                json={"status": "CANCELLED", "exception_reason": "Tentativa cross-store"},
            )
            assert foreign_transition.status_code == missing_transition.status_code == 404
            assert foreign_transition.json() == missing_transition.json()

            db.expire_all()
            after_foreign_state = db.query(models.ReplenishmentTask).filter_by(
                id=foreign_task_id
            ).one().status
            assert after_foreign_state == before_foreign_state
            assert db.query(models.ReplenishmentTaskEvent).filter_by(
                task_id=foreign_task_id
            ).count() == before_foreign_event_count

            scoped_list = client.get("/api/v1/tasks", params={"store_id": foreign_store_id})
            assert scoped_list.status_code == 403



def test_bearer_middleware_authenticates_active_users_and_rejects_invalid_or_inactive(monkeypatch):
    with TestingSession() as db:
        store = models.Store(code="AUTH-STORE", name="Loja autenticação")
        db.add(store)
        db.flush()
        active = models.User(
            email="bearer-active@example.test",
            full_name="Utilizador ativo",
            password_hash="test-only-not-used",
            role="EMPLOYEE",
            store_id=store.id,
            is_active=True,
        )
        inactive = models.User(
            email="bearer-inactive@example.test",
            full_name="Utilizador inativo",
            password_hash="test-only-not-used",
            role="SUPERVISOR",
            store_id=store.id,
            is_active=False,
        )
        db.add_all([active, inactive])
        db.commit()
        db.refresh(active)
        db.refresh(inactive)
        active_id = active.id
        inactive_id = inactive.id

    monkeypatch.setattr(main_module.settings, "app_env", "development")
    monkeypatch.setattr(main_module, "SessionLocal", TestingSession)
    active_token, _ = create_access_token(user_id=active_id, role="SUPERVISOR")
    inactive_token, _ = create_access_token(user_id=inactive_id, role="SUPERVISOR")

    with TestClient(app) as client:
        missing = client.get("/api/v1/auth/me")
        assert missing.status_code == 401
        assert missing.headers.get("www-authenticate") == "Bearer"

        malformed = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not-a-valid-token"},
        )
        assert malformed.status_code == 401

        inactive_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {inactive_token}"},
        )
        assert inactive_response.status_code == 401

        authenticated = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {active_token}"},
        )
        assert authenticated.status_code == 200
        assert authenticated.json()["id"] == active_id
        assert authenticated.json()["role"] == "EMPLOYEE"

        forbidden_role = client.post(
            "/api/v1/shelf-images/1/ocr-runs",
            headers={"Authorization": f"Bearer {active_token}"},
            json={"provider": "test", "model_version": "v1", "regions": []},
        )
        assert forbidden_role.status_code == 403



def test_pallet_lifecycle_audit_endpoints_enforce_store_scope(monkeypatch):
    from types import SimpleNamespace

    db = TestingSession()
    own_store = models.Store(code="PAL-AUDIT-OWN", name="Loja própria")
    foreign_store = models.Store(code="PAL-AUDIT-FOREIGN", name="Loja externa")
    db.add_all([own_store, foreign_store])
    db.flush()

    product = models.Product(sku="PAL-AUDIT-SKU", name="Produto auditoria")
    db.add(product)
    db.flush()
    packaging = models.ProductPackagingLevel(
        product_id=product.id,
        code="PAL",
        name="Palete",
        package_type="PALLET",
        base_units_per_package=100,
    )
    db.add(packaging)
    db.flush()

    own_pallet = models.StorePallet(
        store_id=own_store.id,
        product_id=product.id,
        packaging_level_id=packaging.id,
        pallet_code="OWN-001",
        base_quantity=80,
        status="READY",
        location_type="WAREHOUSE",
    )
    foreign_pallet = models.StorePallet(
        store_id=foreign_store.id,
        product_id=product.id,
        packaging_level_id=packaging.id,
        pallet_code="FOREIGN-001",
        base_quantity=80,
        status="READY",
        location_type="WAREHOUSE",
    )
    db.add_all([own_pallet, foreign_pallet])
    db.flush()

    db.add_all([
        models.PalletRotationEvent(
            pallet_id=own_pallet.id,
            event_type="REGISTERED",
            quantity_before=80,
            quantity_after=80,
            to_location_type="WAREHOUSE",
        ),
        models.PalletRotationEvent(
            pallet_id=foreign_pallet.id,
            event_type="REGISTERED",
            quantity_before=80,
            quantity_after=80,
            to_location_type="WAREHOUSE",
        ),
    ])
    own_store_id, foreign_store_id = own_store.id, foreign_store.id
    own_pallet_id, foreign_pallet_id = own_pallet.id, foreign_pallet.id
    db.commit()
    db.close()

    with TestingSession() as state_db:
        foreign_pallet_before = state_db.get(models.StorePallet, foreign_pallet_id)
        foreign_status_before = foreign_pallet_before.status
        foreign_event_count_before = state_db.query(models.PalletRotationEvent).filter_by(
            pallet_id=foreign_pallet_id
        ).count()

    supervisor = SimpleNamespace(role="SUPERVISOR", store_id=own_store_id, id=None)
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: supervisor)

    with TestClient(app) as client:
        own_events = client.get(
            f"/api/v1/warehouse/pallets/{own_pallet_id}/events",
            params={"store_id": own_store_id},
        )
        assert own_events.status_code == 200
        assert len(own_events.json()) == 1
        assert own_events.json()[0]["event_type"] == "REGISTERED"

        foreign_events = client.get(
            f"/api/v1/warehouse/pallets/{foreign_pallet_id}/events",
            params={"store_id": foreign_store_id},
        )
        assert foreign_events.status_code == 403

        forged_store_filter = client.get(
            f"/api/v1/warehouse/pallets/{foreign_pallet_id}/events",
            params={"store_id": own_store_id},
        )
        assert forged_store_filter.status_code == 404

        foreign_update = client.post(
            f"/api/v1/warehouse/pallets/{foreign_pallet_id}/events",
            json={
                "expected_status": "READY",
                "expected_base_quantity": 80,
                "status": "ON_DISPLAY",
                "location_type": "SALES_FLOOR",
                "location_code": "A-01",
                "reason": "Colocação na exposição",
            },
        )
        assert foreign_update.status_code == 404

        with TestingSession() as state_db:
            foreign_pallet_after = state_db.get(models.StorePallet, foreign_pallet_id)
            assert foreign_pallet_after.status == foreign_status_before
            assert state_db.query(models.PalletRotationEvent).filter_by(
                pallet_id=foreign_pallet_id
            ).count() == foreign_event_count_before

        own_update = client.post(
            f"/api/v1/warehouse/pallets/{own_pallet_id}/events",
            json={
                "expected_status": "READY",
                "expected_base_quantity": 80,
                "status": "ON_DISPLAY",
                "location_type": "SALES_FLOOR",
                "location_code": "A-01",
                "reason": "Colocação na exposição",
            },
        )
        assert own_update.status_code == 201
        assert own_update.json()["event_type"] == "STATUS_REVIEWED"

        own_events_after = client.get(
            f"/api/v1/warehouse/pallets/{own_pallet_id}/events",
            params={"store_id": own_store_id},
        )
        assert own_events_after.status_code == 200
        assert [event["event_type"] for event in own_events_after.json()] == [
            "REGISTERED",
            "STATUS_REVIEWED",
        ]



def test_user_management_endpoints_require_admin_role_and_hash_password(monkeypatch):
    with TestingSession() as db:
        store = models.Store(code="USER-ADMIN-STORE", name="Loja gestão utilizadores")
        db.add(store)
        db.flush()
        admin = models.User(
            email="user-admin@example.test",
            full_name="Administrador",
            password_hash="test-only-not-used",
            role="ADMIN",
            store_id=None,
            is_active=True,
        )
        supervisor = models.User(
            email="user-supervisor@example.test",
            full_name="Supervisor",
            password_hash="test-only-not-used",
            role="SUPERVISOR",
            store_id=store.id,
            is_active=True,
        )
        employee = models.User(
            email="user-employee@example.test",
            full_name="Colaborador",
            password_hash="test-only-not-used",
            role="EMPLOYEE",
            store_id=store.id,
            is_active=True,
        )
        db.add_all([admin, supervisor, employee])
        db.commit()
        db.refresh(admin)
        db.refresh(supervisor)
        db.refresh(employee)
        admin_id, supervisor_id, employee_id = admin.id, supervisor.id, employee.id
        store_id = store.id

    monkeypatch.setattr(main_module.settings, "app_env", "development")
    monkeypatch.setattr(main_module, "SessionLocal", TestingSession)
    admin_token, _ = create_access_token(user_id=admin_id, role="EMPLOYEE")
    supervisor_token, _ = create_access_token(user_id=supervisor_id, role="ADMIN")
    employee_token, _ = create_access_token(user_id=employee_id, role="ADMIN")

    headers = lambda token: {"Authorization": f"Bearer {token}"}
    payload = {
        "email": "  new.employee@example.test ",
        "full_name": "Novo colaborador",
        "password": "Strong-Test-Password-2026!",
        "role": "EMPLOYEE",
        "store_id": store_id,
    }

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/auth/users",
            headers=headers(admin_token),
            json=payload,
        )
        assert created.status_code == 201
        created_user = created.json()
        assert created_user["email"] == "new.employee@example.test"
        assert created_user["role"] == "EMPLOYEE"
        assert created_user["store_id"] == store_id
        assert "password" not in created_user
        assert "password_hash" not in created_user

        with TestingSession() as db:
            stored_user = db.query(models.User).filter_by(
                email="new.employee@example.test"
            ).one()
            assert stored_user.password_hash != payload["password"]
            assert main_module.verify_password(
                payload["password"], stored_user.password_hash
            )

        listed = client.get("/api/v1/auth/users", headers=headers(admin_token))
        assert listed.status_code == 200
        assert any(user["id"] == created_user["id"] for user in listed.json())

        duplicate = client.post(
            "/api/v1/auth/users",
            headers=headers(admin_token),
            json=payload,
        )
        assert duplicate.status_code == 409

        for token in (supervisor_token, employee_token):
            denied_create = client.post(
                "/api/v1/auth/users",
                headers=headers(token),
                json={
                    **payload,
                    "email": "forbidden-create@example.test",
                },
            )
            assert denied_create.status_code == 403
            denied_list = client.get(
                "/api/v1/auth/users",
                headers=headers(token),
            )
            assert denied_list.status_code == 403



def test_partial_task_completion_rejects_whitespace_only_reason_without_changing_task():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        created = client.post("/api/v1/tasks", json={
            "store_id": store_id,
            "shelf_id": shelf_id,
            "product_id": product_id,
            "requested_quantity": 8,
        })
        assert created.status_code == 201
        task_id = created.json()["id"]
        assert client.patch(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": "ASSIGNED", "assigned_to": "ana"},
        ).status_code == 200
        assert client.patch(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": "IN_PROGRESS"},
        ).status_code == 200

        response = client.patch(
            f"/api/v1/tasks/{task_id}/status",
            json={
                "status": "COMPLETED",
                "actual_quantity": 5,
                "exception_reason": "   \t  ",
            },
        )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "EXCEPTION_REASON_TOO_SHORT"
        task = next(
            item for item in client.get("/api/v1/tasks").json()
            if item["id"] == task_id
        )
        assert task["status"] == "IN_PROGRESS"
        assert task["actual_quantity"] is None
        assert client.get(f"/api/v1/tasks/{task_id}/events").json()[-1]["to_status"] == "IN_PROGRESS"


def test_task_cancellation_rejects_whitespace_only_reason_without_changing_task():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        created = client.post("/api/v1/tasks", json={
            "store_id": store_id,
            "shelf_id": shelf_id,
            "product_id": product_id,
        })
        assert created.status_code == 201
        task_id = created.json()["id"]

        response = client.patch(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": "CANCELLED", "exception_reason": "   "},
        )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "EXCEPTION_REASON_TOO_SHORT"
        task = next(
            item for item in client.get("/api/v1/tasks").json()
            if item["id"] == task_id
        )
        assert task["status"] == "PENDING"
        events = client.get(f"/api/v1/tasks/{task_id}/events").json()
        assert [event["to_status"] for event in events] == ["PENDING"]


def test_task_exception_reason_is_trimmed_before_persistence_and_audit():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        created = client.post("/api/v1/tasks", json={
            "store_id": store_id,
            "shelf_id": shelf_id,
            "product_id": product_id,
        })
        assert created.status_code == 201
        task_id = created.json()["id"]

        response = client.patch(
            f"/api/v1/tasks/{task_id}/status",
            json={
                "status": "CANCELLED",
                "exception_reason": "  Produto descontinuado  ",
            },
        )

        assert response.status_code == 200
        assert response.json()["exception_reason"] == "Produto descontinuado"
        event = client.get(f"/api/v1/tasks/{task_id}/events").json()[-1]
        assert event["reason"] == "Produto descontinuado"


@pytest.mark.parametrize(
    ("snapshot_offset", "expected_status"),
    [
        (timedelta(days=-2), "STALE_INVENTORY"),
        (timedelta(minutes=5), "INVALID_INVENTORY_TIMESTAMP"),
    ],
)
def test_replenishment_rejects_stale_or_future_inventory_snapshot(
    snapshot_offset, expected_status
):
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id,
            "source": "simulation",
            "status": "LOW_STOCK",
            "confidence": 0.99,
        })
        assert observation.status_code == 201, observation.text

        snapshot = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id,
            "product_id": product_id,
            "on_hand_quantity": 20,
            "reserved_quantity": 0,
            "source": "WMS",
            "captured_at": (datetime.now(timezone.utc) + snapshot_offset).isoformat(),
        })
        assert snapshot.status_code == 201, snapshot.text

        recommendations = client.get(
            "/api/v1/replenishment/recommendations",
            params={"store_id": store_id, "product_id": product_id},
        )
        assert recommendations.status_code == 200, recommendations.text
        recommendation = recommendations.json()[0]
        assert recommendation["recommendation_status"] == expected_status
        assert recommendation["suggested_quantity"] is None

        task = client.post("/api/v1/tasks/from-recommendation", json={
            "store_id": store_id,
            "shelf_id": shelf_id,
            "product_id": product_id,
            "requested_quantity": 2,
        })
        assert task.status_code == 409, task.text


def test_replenishment_uses_store_and_source_inventory_freshness_policy():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_task_context(client)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id,
            "source": "simulation",
            "status": "LOW_STOCK",
            "confidence": 0.99,
        })
        assert observation.status_code == 201, observation.text

        snapshot = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id,
            "product_id": product_id,
            "on_hand_quantity": 20,
            "reserved_quantity": 0,
            "source": "WMS",
            "captured_at": (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
        })
        assert snapshot.status_code == 201, snapshot.text

        with TestingSession() as db:
            db.add(models.InventoryFreshnessPolicy(
                store_id=store_id,
                source="WMS",
                max_age_minutes=10,
            ))
            db.commit()

        response = client.get(
            "/api/v1/replenishment/recommendations",
            params={"store_id": store_id, "product_id": product_id},
        )
        assert response.status_code == 200, response.text
        recommendation = response.json()[0]
        assert recommendation["recommendation_status"] == "STALE_INVENTORY"
        assert recommendation["suggested_quantity"] is None


def test_auto_assign_balances_workload_and_prioritizes_urgent_tasks(monkeypatch):
    with TestClient(app) as client:
        store_id, shelf_id, _ = create_task_context(client)
        db = TestingSession()
        try:
            supervisor = models.User(
                email=f"supervisor-{uuid4().hex}@example.test",
                store_id=store_id,
                full_name="Supervisor",
                password_hash="test-only-not-used",
                role="SUPERVISOR",
                is_active=True,
            )
            employee_one = models.User(
                email=f"employee-one-{uuid4().hex}@example.test",
                store_id=store_id,
                full_name="Ana",
                password_hash="test-only-not-used",
                role="EMPLOYEE",
                is_active=True,
            )
            employee_two = models.User(
                email=f"employee-two-{uuid4().hex}@example.test",
                store_id=store_id,
                full_name="Bruno",
                password_hash="test-only-not-used",
                role="EMPLOYEE",
                is_active=True,
            )
            db.add_all([supervisor, employee_one, employee_two])
            db.commit()
            db.refresh(supervisor)
            db.refresh(employee_one)
            db.refresh(employee_two)
            supervisor_id = supervisor.id
            employee_one_id = employee_one.id
            employee_two_id = employee_two.id
        finally:
            db.close()

        monkeypatch.setattr(
            main_module, "_request_user",
            lambda _db, _request: models.User(
                id=supervisor_id, store_id=store_id, role="SUPERVISOR", is_active=True,
            ),
        )

        product_ids = []
        for index in range(3):
            product = client.post("/api/v1/products", json={
                "sku": f"AUTO-{index}-{uuid4().hex[:6]}",
                "name": f"Produto automático {index}",
            })
            assert product.status_code == 201, product.text
            product_id = product.json()["id"]
            product_ids.append(product_id)
            linked = client.post("/api/v1/shelf-products", json={
                "shelf_id": shelf_id, "product_id": product_id,
                "target_quantity": 10, "min_display_quantity": 2,
            })
            assert linked.status_code == 201, linked.text

        baseline = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_ids[0],
            "priority": "LOW", "assigned_user_id": employee_one_id,
        })
        assert baseline.status_code == 201, baseline.text
        baseline_assigned = client.patch(
            f"/api/v1/tasks/{baseline.json()['id']}/status",
            json={
                "status": "ASSIGNED",
                "assigned_user_id": employee_one_id,
                "assigned_to": "Ana",
            },
        )
        assert baseline_assigned.status_code == 200, baseline_assigned.text
        urgent = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_ids[1],
            "priority": "URGENT",
        })
        normal = client.post("/api/v1/tasks", json={
            "store_id": store_id, "shelf_id": shelf_id, "product_id": product_ids[2],
            "priority": "NORMAL",
        })
        assert urgent.status_code == 201, urgent.text
        assert normal.status_code == 201, normal.text

        response = client.post(
            "/api/v1/replenishment/auto-assign",
            params={"store_id": store_id},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["assigned_count"] == 2
        by_task = {item["task_id"]: item["assigned_user_id"] for item in result["assignments"]}
        assert by_task[urgent.json()["id"]] == employee_two_id
        assert by_task[normal.json()["id"]] == employee_one_id

        events = client.get(f"/api/v1/tasks/{urgent.json()['id']}/events")
        assert events.status_code == 200
        assert events.json()[-1]["to_status"] == "ASSIGNED"
        assert events.json()[-1]["reason"].startswith("Distribuição automática")
