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
        assert body["zone_summaries"][0]["zone_name"] == "Bebidas"
        assert body["zone_summaries"][0]["high_priority"] == 1
        assert body["zone_summaries"][0]["urgent_items"][0]["product_sku"] == "DEC-SKU-02"


def test_backroom_snapshot_is_not_misused_as_shelf_inventory_or_coverage():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "EMPTY", "confidence": 0.99,
        })
        assert observation.status_code == 201
        snapshot = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 20, "reserved_quantity": 5,
            "source": "MANUAL", "external_reference": "BACKROOM-TEST-01",
        })
        assert snapshot.status_code == 201

        response = client.get("/api/v1/operational-decisions", params={"store_id": store_id})
        assert response.status_code == 200
        item = response.json()["decisions"][0]
        decision = item["decision"]
        assert decision["status"] == "ACTION_RECOMMENDED"
        assert decision["suggested_replenishment_quantity"] is None
        assert decision["inventory_coverage_hours"] is None
        assert item["backroom_inventory"]["on_hand_quantity"] == 20
        assert item["backroom_inventory"]["reserved_quantity"] == 5
        assert item["backroom_inventory"]["available_quantity"] == 15
        assert any("retaguarda" in warning for warning in decision["warnings"])


def test_operational_decision_proposes_partial_refill_only_from_fresh_measured_evidence():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "LOW_STOCK", "confidence": 0.98,
            "observed_quantity": 2,
        })
        assert observation.status_code == 201
        snapshot = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 8, "reserved_quantity": 3,
            "source": "MANUAL", "external_reference": "REFILL-PARTIAL-01",
        })
        assert snapshot.status_code == 201

        response = client.get("/api/v1/operational-decisions", params={"store_id": store_id})
        assert response.status_code == 200
        item = response.json()["decisions"][0]
        assessment = item["replenishment_assessment"]
        assert assessment["status"] == "NEEDS_REPLENISHMENT"
        assert assessment["shelf_gap_quantity"] == 10
        assert assessment["suggested_quantity"] == 5
        assert assessment["remaining_gap_quantity"] == 5
        assert assessment["requires_human_review"] is True
        assert item["backroom_inventory"]["is_fresh"] is True


def test_operational_decision_never_uses_stale_backroom_stock_for_refill_quantity():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "EMPTY", "confidence": 0.99,
            "observed_quantity": 0,
        })
        assert observation.status_code == 201
        snapshot = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 30, "reserved_quantity": 0,
            "source": "MANUAL", "external_reference": "REFILL-STALE-01",
            "captured_at": "2020-01-01T00:00:00Z",
        })
        assert snapshot.status_code == 201

        response = client.get("/api/v1/operational-decisions", params={"store_id": store_id})
        assert response.status_code == 200
        item = response.json()["decisions"][0]
        assessment = item["replenishment_assessment"]
        assert item["backroom_inventory"]["is_fresh"] is False
        assert assessment["status"] == "INVENTORY_UNKNOWN"
        assert assessment["suggested_quantity"] is None
        assert assessment["requires_human_review"] is True


def test_future_observation_and_future_inventory_are_not_accepted_for_refill():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "EMPTY", "confidence": 0.99,
            "observed_quantity": 0,
            "observed_at": "2099-01-01T00:00:00Z",
        })
        assert observation.status_code == 201
        snapshot = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 30, "reserved_quantity": 0,
            "source": "MANUAL", "external_reference": "REFILL-FUTURE-01",
            "captured_at": "2099-01-01T00:00:00Z",
        })
        assert snapshot.status_code == 201

        response = client.get("/api/v1/operational-decisions", params={"store_id": store_id})
        assert response.status_code == 200
        item = response.json()["decisions"][0]
        assert item["backroom_inventory"]["is_fresh"] is False
        assert item["replenishment_assessment"]["status"] == "FUTURE_OBSERVATION"
        assert item["replenishment_assessment"]["suggested_quantity"] is None


def test_operational_decision_task_requires_explicit_approval_and_revalidates_evidence():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        observation = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "LOW_STOCK", "confidence": 0.98,
            "observed_quantity": 2,
        })
        assert observation.status_code == 201
        snapshot = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 8, "reserved_quantity": 3,
            "source": "MANUAL", "external_reference": "APPROVAL-01",
        })
        assert snapshot.status_code == 201

        payload = {
            "store_id": store_id, "shelf_id": shelf_id,
            "product_id": product_id, "priority": "HIGH",
        }
        rejected = client.post("/api/v1/tasks/from-operational-decision", json=payload)
        assert rejected.status_code == 400
        assert rejected.json()["detail"]["code"] == "HUMAN_APPROVAL_REQUIRED"
        assert client.get("/api/v1/tasks", params={"store_id": store_id}).json() == []

        created = client.post(
            "/api/v1/tasks/from-operational-decision?approved=true", json=payload,
        )
        assert created.status_code == 201
        task = created.json()
        assert task["requested_quantity"] == 5
        assert task["status"] == "PENDING"
        assert "Aprovado manualmente" in task["notes"]
        audit = client.get(f"/api/v1/tasks/{task['id']}/events")
        assert audit.status_code == 200
        assert [event["event_type"] for event in audit.json()] == ["CREATED", "APPROVED"]
        assert audit.json()[0]["from_status"] is None
        assert audit.json()[0]["to_status"] == "PENDING"
        assert audit.json()[1]["actual_quantity"] == 5

        duplicate = client.post(
            "/api/v1/tasks/from-operational-decision?approved=true", json=payload,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "ACTIVE_TASK_EXISTS"


def test_operational_decision_task_cannot_exceed_validated_refill_quantity():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "LOW_STOCK", "confidence": 0.98,
            "observed_quantity": 2,
        })
        client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 8, "reserved_quantity": 3,
            "source": "MANUAL", "external_reference": "APPROVAL-02",
        })
        response = client.post(
            "/api/v1/tasks/from-operational-decision?approved=true",
            json={
                "store_id": store_id, "shelf_id": shelf_id,
                "product_id": product_id, "requested_quantity": 6,
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "REQUEST_EXCEEDS_APPROVED_QUANTITY"
        assert client.get("/api/v1/tasks", params={"store_id": store_id}).json() == []


def test_task_approval_rechecks_latest_stock_and_refuses_when_backroom_is_empty():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "EMPTY", "confidence": 0.99,
            "observed_quantity": 0,
        })
        first = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 12, "reserved_quantity": 0,
            "source": "MANUAL", "external_reference": "APPROVAL-STOCK-01",
        })
        assert first.status_code == 201
        changed = client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 0, "reserved_quantity": 0,
            "source": "MANUAL", "external_reference": "APPROVAL-STOCK-02",
        })
        assert changed.status_code == 201

        response = client.post(
            "/api/v1/tasks/from-operational-decision?approved=true",
            json={
                "store_id": store_id, "shelf_id": shelf_id,
                "product_id": product_id,
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "REPLENISHMENT_NOT_APPROVED_BY_EVIDENCE"
        assert client.get("/api/v1/tasks", params={"store_id": store_id}).json() == []


def test_task_approval_refuses_status_only_detection_without_measured_shelf_quantity():
    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "EMPTY", "confidence": 0.99,
        })
        client.post("/api/v1/inventory/snapshots", json={
            "store_id": store_id, "product_id": product_id,
            "on_hand_quantity": 12, "reserved_quantity": 0,
            "source": "MANUAL", "external_reference": "APPROVAL-NO-COUNT-01",
        })
        response = client.post(
            "/api/v1/tasks/from-operational-decision?approved=true",
            json={
                "store_id": store_id, "shelf_id": shelf_id,
                "product_id": product_id,
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "REPLENISHMENT_NOT_APPROVED_BY_EVIDENCE"
        assert client.get("/api/v1/tasks", params={"store_id": store_id}).json() == []

def test_stale_visual_observation_does_not_trigger_action_recommended():
    from datetime import datetime, timedelta, timezone

    with TestClient(app) as client:
        store_id, shelf_id, product_id = create_context(client)
        created = client.post("/api/v1/observations", json={
            "shelf_id": shelf_id, "source": "simulation",
            "status": "EMPTY", "confidence": 0.96,
        })
        assert created.status_code == 201

        db = TestingSession()
        try:
            observation = db.query(models.Observation).filter_by(
                id=created.json()["id"]
            ).one()
            observation.observed_at = datetime.now(timezone.utc) - timedelta(minutes=150)
            db.commit()
        finally:
            db.close()

        response = client.get(
            "/api/v1/operational-decisions", params={"store_id": store_id}
        )
        assert response.status_code == 200
        item = response.json()["decisions"][0]
        assert item["product_id"] == product_id
        assert item["decision"]["status"] == "MONITOR"
        assert item["decision"]["priority"] == "NONE"
        assert item["replenishment_assessment"]["status"] == "STALE_OBSERVATION"
        assert item["decision"]["suggested_replenishment_quantity"] is None
