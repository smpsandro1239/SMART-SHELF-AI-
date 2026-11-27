"""Fenced, transactional application of authenticated Edge task acknowledgements.

This module is deliberately not registered as a worker handler yet.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.edge_event_worker import EdgeEventHandlerError


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EdgeEventHandlerError("INVALID_EVENT_TIMESTAMP", retryable=False)
    return value.astimezone(timezone.utc)


def apply_edge_task_acknowledgement(db: Session, event: dict) -> None:
    """Persist an authorized device declaration; never mutate task or inventory."""
    if event.get("event_type") != "TASK_ACKNOWLEDGED":
        raise EdgeEventHandlerError("INVALID_HANDLER_ROUTING", retryable=False)

    payload = event.get("payload")
    if not isinstance(payload, dict) or set(payload) != {"task_id", "task_version", "action"}:
        raise EdgeEventHandlerError("INVALID_ACK_PAYLOAD", retryable=False)

    task_id = payload["task_id"]
    task_version = payload["task_version"]
    action = payload["action"]
    if type(task_id) is not int or task_id <= 0 or type(task_version) is not int or task_version <= 0:
        raise EdgeEventHandlerError("INVALID_ACK_PAYLOAD", retryable=False)
    if action not in {"ACCEPTED", "STARTED", "COMPLETED"}:
        raise EdgeEventHandlerError("INVALID_ACK_ACTION", retryable=False)

    store_id = event.get("store_id")
    device_id = event.get("device_id")
    inbox_id = event.get("inbox_id")
    event_id = event.get("event_id")
    sequence_number = event.get("sequence_number")
    fingerprint = event.get("fingerprint_sha256")
    occurred_at = _utc(event["occurred_at"])
    received_at = datetime.now(timezone.utc)

    # Lock order matches the assignment service. Processing row is already
    # locked by complete_edge_event_transactionally before this handler runs.
    store = db.query(models.Store).filter(models.Store.id == store_id).with_for_update().populate_existing().first()
    if store is None:
        raise EdgeEventHandlerError("ACK_NOT_AUTHORIZED", retryable=False)

    task = (db.query(models.ReplenishmentTask)
        .filter(models.ReplenishmentTask.id == task_id,
                models.ReplenishmentTask.store_id == store_id)
        .with_for_update().populate_existing().first())
    if task is None:
        raise EdgeEventHandlerError("ACK_NOT_AUTHORIZED", retryable=False)
    if task.task_version != task_version:
        raise EdgeEventHandlerError("STALE_TASK_VERSION", retryable=False)

    device = (db.query(models.EdgeDevice)
        .filter(models.EdgeDevice.device_id == device_id,
                models.EdgeDevice.store_id == store_id)
        .with_for_update().populate_existing().first())
    if device is None or device.status != "ACTIVE":
        raise EdgeEventHandlerError("DEVICE_NOT_ALLOWED", retryable=False)

    assignment = (db.query(models.EdgeDeviceTaskAssignment)
        .filter(models.EdgeDeviceTaskAssignment.store_id == store_id,
                models.EdgeDeviceTaskAssignment.task_id == task_id,
                models.EdgeDeviceTaskAssignment.device_id == device_id)
        .with_for_update().populate_existing().first())
    if (
        assignment is None or assignment.revoked_at is not None
        or assignment.task_version != task_version
        or assignment.valid_from > received_at
        or (assignment.valid_until is not None and assignment.valid_until <= received_at)
        or assignment.valid_from > occurred_at
        or (assignment.valid_until is not None and assignment.valid_until <= occurred_at)
    ):
        raise EdgeEventHandlerError("UNASSIGNED_DEVICE", retryable=False)

    if db.query(models.EdgeTaskAcknowledgement.id).filter(
        models.EdgeTaskAcknowledgement.device_id == device_id,
        models.EdgeTaskAcknowledgement.event_id == event_id,
    ).first():
        raise EdgeEventHandlerError("DUPLICATE_ACK_EVENT", retryable=False)

    result = "REVIEW_REQUIRED" if action == "COMPLETED" else action
    db.add(models.EdgeTaskAcknowledgement(
        store_id=store_id,
        task_id=task_id,
        task_version=task_version,
        device_id=device_id,
        assignment_id=assignment.id,
        inbox_id=inbox_id,
        event_id=event_id,
        sequence_number=sequence_number,
        fingerprint_sha256=fingerprint,
        action=action,
        result=result,
        declared_at=occurred_at,
        received_at=received_at,
    ))
    db.flush()
