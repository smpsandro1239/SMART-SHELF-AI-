"""Tests for the append-only Edge task acknowledgement service."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.edge_task_acknowledgement_service import apply_edge_task_acknowledgement
from app.edge_task_assignment_service import create_edge_task_assignment


@pytest.fixture()
def ack_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    store = models.Store(code="EDGE-ACK-STORE", name="Loja ACK")
    db.add(store)
    db.flush()
    user = models.User(
        email="ack-supervisor@example.test", store_id=store.id, full_name="Supervisora",
        password_hash="not-a-real-password-hash", role="SUPERVISOR", is_active=True,
    )
    zone = models.Zone(store_id=store.id, name="Bebidas")
    product = models.Product(sku="SKU-ACK-1", name="Água", unit="un")
    device = models.EdgeDevice(device_id="edge-ack-device", store_id=store.id,
                               device_type="robot", status="ACTIVE")
    db.add_all([user, zone, product, device])
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="ACK-01")
    db.add(shelf)
    db.flush()
    task = models.ReplenishmentTask(store_id=store.id, shelf_id=shelf.id,
                                    product_id=product.id, status="PENDING", priority="NORMAL")
    db.add(task)
    db.commit()
    now = datetime.now(timezone.utc)
    assignment = create_edge_task_assignment(
        db, store_id=store.id, task_id=task.id, device_id=device.device_id,
        actor=user, reason="Associação para teste ACK", valid_from=now - timedelta(minutes=1),
        valid_until=now + timedelta(hours=1),
    )
    inbox = models.EdgeDeviceEventInbox(
        device_id=device.device_id,
        event_id="00000000-0000-4000-8000-000000000103",
        sequence_number=3, event_type="TASK_ACKNOWLEDGED", store_id=store.id,
        shelf_id=None, occurred_at=now,
        payload={"task_id": task.id, "task_version": task.task_version, "action": "COMPLETED"},
        fingerprint_sha256="a" * 64, received_at=now,
    )
    db.add(inbox)
    db.commit()
    event = {
        "event_type": "TASK_ACKNOWLEDGED", "store_id": store.id,
        "device_id": device.device_id, "inbox_id": inbox.id, "event_id": inbox.event_id,
        "sequence_number": inbox.sequence_number, "fingerprint_sha256": inbox.fingerprint_sha256,
        "occurred_at": now, "payload": inbox.payload,
    }
    yield db, task.id, event
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_completed_ack_is_review_evidence_only(ack_db):
    db, task_id, event = ack_db
    before = db.get(models.ReplenishmentTask, task_id)
    original_status = before.status
    original_version = before.task_version

    apply_edge_task_acknowledgement(db, event)
    db.commit()

    row = db.query(models.EdgeTaskAcknowledgement).one()
    assert row.action == "COMPLETED"
    assert row.result == "REVIEW_REQUIRED"
    assert row.fingerprint_sha256 == "a" * 64
    task = db.get(models.ReplenishmentTask, task_id)
    assert task.status == original_status
    assert task.task_version == original_version
    assert task.completed_at is None
    assert db.query(models.InventoryMovement).count() == 0


def test_acknowledgement_rejects_stale_task_version(ack_db):
    db, task_id, event = ack_db
    event["payload"] = {**event["payload"], "task_version": event["payload"]["task_version"] + 1}
    from app.edge_event_worker import EdgeEventHandlerError
    with pytest.raises(EdgeEventHandlerError) as error:
        apply_edge_task_acknowledgement(db, event)
    assert error.value.code == "STALE_TASK_VERSION"
    assert db.query(models.EdgeTaskAcknowledgement).count() == 0


def test_acknowledgement_requires_active_assignment(ack_db):
    db, task_id, event = ack_db
    assignment = db.query(models.EdgeDeviceTaskAssignment).one()
    assignment.revoked_at = datetime.now(timezone.utc)
    assignment.revoked_by_user_id = db.query(models.User).filter_by(role="SUPERVISOR").one().id
    assignment.revocation_reason = "Revogada para teste"
    db.commit()
    from app.edge_event_worker import EdgeEventHandlerError
    with pytest.raises(EdgeEventHandlerError) as error:
        apply_edge_task_acknowledgement(db, event)
    assert error.value.code == "UNASSIGNED_DEVICE"
    assert db.query(models.EdgeTaskAcknowledgement).count() == 0


@pytest.mark.parametrize("invalid_action", [None, 7, [], {}, True])
def test_acknowledgement_rejects_non_string_action(ack_db, invalid_action):
    db, _task_id, event = ack_db
    event["payload"] = {**event["payload"], "action": invalid_action}
    from app.edge_event_errors import EdgeEventHandlerError

    with pytest.raises(EdgeEventHandlerError) as error:
        apply_edge_task_acknowledgement(db, event)

    assert error.value.code == "INVALID_ACK_ACTION"
    assert db.query(models.EdgeTaskAcknowledgement).count() == 0


@pytest.mark.parametrize(
    ("identity_override", "expected_code"),
    [
        ("foreign_task", "ACK_NOT_AUTHORIZED"),
        ("foreign_device", "DEVICE_NOT_ALLOWED"),
        ("foreign_store_local_task", "ACK_NOT_AUTHORIZED"),
        ("foreign_store_foreign_task_device", "UNASSIGNED_DEVICE"),
    ],
)
def test_acknowledgement_rejects_cross_store_identity(ack_db, identity_override, expected_code):
    db, _local_task_id, event = ack_db
    local_store_id = event["store_id"]

    foreign_store = models.Store(code="EDGE-ACK-FOREIGN", name="Loja estrangeira")
    db.add(foreign_store)
    db.flush()
    foreign_zone = models.Zone(store_id=foreign_store.id, name="Zona estrangeira")
    foreign_device = models.EdgeDevice(
        device_id="edge-ack-foreign-device",
        store_id=foreign_store.id,
        device_type="robot",
        status="ACTIVE",
    )
    db.add_all([foreign_zone, foreign_device])
    db.flush()
    foreign_shelf = models.Shelf(zone_id=foreign_zone.id, code="ACK-FOREIGN-01")
    db.add(foreign_shelf)
    db.flush()
    foreign_task = models.ReplenishmentTask(
        store_id=foreign_store.id,
        shelf_id=foreign_shelf.id,
        product_id=db.query(models.Product.id).filter_by(sku="SKU-ACK-1").scalar(),
        status="PENDING",
        priority="NORMAL",
    )
    db.add(foreign_task)
    db.commit()

    if identity_override == "foreign_task":
        event["payload"] = {**event["payload"], "task_id": foreign_task.id}
    elif identity_override == "foreign_device":
        event["device_id"] = foreign_device.device_id
    elif identity_override == "foreign_store_local_task":
        event["store_id"] = foreign_store.id
    else:
        event["store_id"] = foreign_store.id
        event["payload"] = {**event["payload"], "task_id": foreign_task.id}
        event["device_id"] = foreign_device.device_id

    from app.edge_event_errors import EdgeEventHandlerError
    with pytest.raises(EdgeEventHandlerError) as error:
        apply_edge_task_acknowledgement(db, event)

    assert error.value.code == expected_code
    assert db.query(models.EdgeTaskAcknowledgement).count() == 0
    assert db.query(models.ReplenishmentTask).filter_by(store_id=local_store_id).one().status == "PENDING"
    assert db.query(models.ReplenishmentTask).filter_by(store_id=foreign_store.id).one().status == "PENDING"
