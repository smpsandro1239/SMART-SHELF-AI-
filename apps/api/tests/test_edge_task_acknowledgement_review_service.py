"""Tests for the append-only human review of Edge completion declarations."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.edge_task_acknowledgement_review_service import (
    EdgeTaskAcknowledgementReviewError,
    record_edge_task_acknowledgement_review,
)
from app.edge_task_acknowledgement_service import apply_edge_task_acknowledgement
from app.edge_task_assignment_service import create_edge_task_assignment


@pytest.fixture()
def review_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    store = models.Store(code="EDGE-REVIEW-STORE", name="Loja revisão")
    db.add(store)
    db.flush()
    supervisor = models.User(
        email="review-supervisor@example.test", store_id=store.id, full_name="Supervisora",
        password_hash="test-only", role="SUPERVISOR", is_active=True,
    )
    employee = models.User(
        email="review-employee@example.test", store_id=store.id, full_name="Funcionário",
        password_hash="test-only", role="EMPLOYEE", is_active=True,
    )
    foreign_store = models.Store(code="EDGE-REVIEW-FOREIGN", name="Loja estrangeira")
    zone = models.Zone(store_id=store.id, name="Bebidas")
    product = models.Product(sku="SKU-REVIEW-1", name="Água", unit="un")
    device = models.EdgeDevice(device_id="edge-review-device", store_id=store.id, device_type="robot", status="ACTIVE")
    db.add_all([supervisor, employee, foreign_store, zone, product, device])
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="REVIEW-01")
    db.add(shelf)
    db.flush()
    task = models.ReplenishmentTask(store_id=store.id, shelf_id=shelf.id, product_id=product.id, status="PENDING")
    db.add(task)
    db.commit()
    now = datetime.now(timezone.utc)
    create_edge_task_assignment(
        db, store_id=store.id, task_id=task.id, device_id=device.device_id, actor=supervisor,
        reason="Associação para revisão", valid_from=now-timedelta(minutes=1),
        valid_until=now+timedelta(hours=1), allowed_actions=["COMPLETED"],
    )
    inbox = models.EdgeDeviceEventInbox(
        device_id=device.device_id, event_id="00000000-0000-4000-8000-000000000104",
        sequence_number=4, event_type="TASK_ACKNOWLEDGED", store_id=store.id, shelf_id=None,
        occurred_at=now, payload={"task_id":task.id,"task_version":task.task_version,"action":"COMPLETED"},
        fingerprint_sha256="b"*64, received_at=now,
    )
    db.add(inbox)
    db.commit()
    event={"event_type":"TASK_ACKNOWLEDGED","store_id":store.id,"device_id":device.device_id,
           "inbox_id":inbox.id,"event_id":inbox.event_id,"sequence_number":inbox.sequence_number,
           "fingerprint_sha256":inbox.fingerprint_sha256,"occurred_at":now,"payload":inbox.payload}
    apply_edge_task_acknowledgement(db,event)
    db.commit()
    ack=db.query(models.EdgeTaskAcknowledgement).one()
    yield db, supervisor, employee, foreign_store, task.id, ack.id
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _record(db, actor, ack_id, **overrides):
    values={"decision":"APPROVED","reason":"Reposição verificada presencialmente",
            "evidence_reference":"evidence://store/shift/123","idempotency_key":"review-key-0001"}
    values.update(overrides)
    return record_edge_task_acknowledgement_review(db, acknowledgement_id=ack_id, actor=actor, **values)


def test_review_is_audit_record_and_does_not_mutate_task_or_inventory(review_db):
    db, actor, _employee, _foreign, task_id, ack_id=review_db
    task=db.get(models.ReplenishmentTask,task_id)
    before=(task.status,task.task_version,task.completed_at)
    review,created=_record(db,actor,ack_id)
    assert created is True
    db.commit()
    assert review.actor_user_id == actor.id
    assert review.decision == "APPROVED"
    assert review.reviewed_at is not None
    task=db.get(models.ReplenishmentTask,task_id)
    assert (task.status,task.task_version,task.completed_at)==before
    assert db.query(models.InventoryMovement).count()==0
    assert db.query(models.EdgeTaskAcknowledgement).one().result=="REVIEW_REQUIRED"
    assert db.query(models.EdgeTaskAcknowledgementReview).count()==1


def test_review_idempotency_returns_same_record_and_rejects_changed_payload(review_db):
    db, actor, _employee, _foreign, _task_id, ack_id=review_db
    first,created=_record(db,actor,ack_id); db.commit()
    replay,replayed=_record(db,actor,ack_id); db.commit()
    assert created is True and replayed is False and replay.id==first.id
    with pytest.raises(EdgeTaskAcknowledgementReviewError) as error:
        _record(db,actor,ack_id,decision="REJECTED")
    assert error.value.code=="IDEMPOTENCY_CONFLICT"


def test_review_denies_employee_inactive_and_cross_store_supervisor(review_db):
    db, actor, employee, foreign_store, _task_id, ack_id=review_db
    with pytest.raises(EdgeTaskAcknowledgementReviewError) as error:
        _record(db,employee,ack_id)
    assert error.value.code=="FORBIDDEN"
    actor.is_active=False
    with pytest.raises(EdgeTaskAcknowledgementReviewError) as error:
        _record(db,actor,ack_id,idempotency_key="review-key-0002")
    assert error.value.code=="ACTOR_INACTIVE"
    actor.is_active=True
    actor.store_id=foreign_store.id
    db.flush()
    with pytest.raises(EdgeTaskAcknowledgementReviewError) as error:
        _record(db,actor,ack_id,idempotency_key="review-key-0003")
    assert error.value.code=="ACK_NOT_FOUND"


def test_review_requires_completed_review_required_ack(review_db):
    db, actor, _employee, _foreign, _task_id, ack_id=review_db
    ack=db.get(models.EdgeTaskAcknowledgement,ack_id)
    ack.action="STARTED"
    ack.result="STARTED"
    db.flush()
    with pytest.raises(EdgeTaskAcknowledgementReviewError) as error:
        _record(db,actor,ack_id,idempotency_key="review-key-0004")
    assert error.value.code=="ACK_NOT_REVIEWABLE"
