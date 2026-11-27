"""Transactional claim/lease lifecycle for immutable Edge event inbox records."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app import models


class EdgeEventProcessingError(RuntimeError):
    """Raised when a worker attempts an invalid or stale processing transition."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def claim_next_edge_event(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int = 60,
    now: datetime | None = None,
) -> dict | None:
    """Claim one eligible event using row locks and a monotonically increasing fence."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", worker_id or ""):
        raise ValueError("worker_id must be 1-160 safe ASCII characters")
    if not 5 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be between 5 and 3600")
    current = _utc(now or _now())
    try:
        exhausted = (
            db.query(models.EdgeDeviceEventProcessing)
            .filter(
                models.EdgeDeviceEventProcessing.attempt_count
                >= models.EdgeDeviceEventProcessing.max_attempts,
                or_(
                    and_(
                        models.EdgeDeviceEventProcessing.status.in_(("PENDING", "RETRY")),
                        models.EdgeDeviceEventProcessing.available_at <= current,
                    ),
                    and_(
                        models.EdgeDeviceEventProcessing.status == "PROCESSING",
                        models.EdgeDeviceEventProcessing.lease_expires_at <= current,
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
            .all()
        )
        for item in exhausted:
            item.status = "DEAD_LETTER"
            item.lease_owner = None
            item.lease_expires_at = None
            item.finished_at = current
            item.last_error_code = item.last_error_code or "MAX_ATTEMPTS_EXCEEDED"
            item.updated_at = current

        item = (
            db.query(models.EdgeDeviceEventProcessing)
            .filter(
                models.EdgeDeviceEventProcessing.attempt_count
                < models.EdgeDeviceEventProcessing.max_attempts,
                or_(
                    and_(
                        models.EdgeDeviceEventProcessing.status.in_(("PENDING", "RETRY")),
                        models.EdgeDeviceEventProcessing.available_at <= current,
                    ),
                    and_(
                        models.EdgeDeviceEventProcessing.status == "PROCESSING",
                        models.EdgeDeviceEventProcessing.lease_expires_at <= current,
                    ),
                ),
            )
            .order_by(models.EdgeDeviceEventProcessing.available_at.asc(),
                      models.EdgeDeviceEventProcessing.id.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
        if item is None:
            db.commit()
            return None

        item.status = "PROCESSING"
        item.attempt_count += 1
        item.fencing_token += 1
        item.lease_owner = worker_id
        item.lease_expires_at = current + timedelta(seconds=lease_seconds)
        item.finished_at = None
        item.updated_at = current
        db.flush()
        inbox = db.get(models.EdgeDeviceEventInbox, item.inbox_id)
        if inbox is None:
            raise EdgeEventProcessingError("processing row references a missing inbox event")
        result = {
            "processing_id": item.id,
            "inbox_id": inbox.id,
            "device_id": inbox.device_id,
            "event_id": inbox.event_id,
            "event_type": inbox.event_type,
            "store_id": inbox.store_id,
            "shelf_id": inbox.shelf_id,
            "sequence_number": inbox.sequence_number,
            "fingerprint_sha256": inbox.fingerprint_sha256,
            "occurred_at": inbox.occurred_at,
            "payload": inbox.payload,
            "attempt_count": item.attempt_count,
            "fencing_token": item.fencing_token,
            "lease_expires_at": item.lease_expires_at,
        }
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise



def renew_edge_event_lease(
    db: Session,
    *,
    processing_id: int,
    worker_id: str,
    fencing_token: int,
    lease_seconds: int = 60,
    now: datetime | None = None,
) -> datetime:
    """Extend the current unexpired lease without allowing stale workers to renew it."""
    if isinstance(processing_id, bool) or not isinstance(processing_id, int) or processing_id <= 0:
        raise ValueError("processing_id must be a positive integer")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", worker_id or ""):
        raise ValueError("worker_id must be 1-160 safe ASCII characters")
    if isinstance(fencing_token, bool) or not isinstance(fencing_token, int) or fencing_token <= 0:
        raise ValueError("fencing_token must be a positive integer")
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 5 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be between 5 and 3600")
    current = _utc(now or _now())
    try:
        item = (
            db.query(models.EdgeDeviceEventProcessing)
            .filter_by(id=processing_id)
            .with_for_update()
            .first()
        )
        if (
            item is None or item.status != "PROCESSING"
            or item.lease_owner != worker_id or item.fencing_token != fencing_token
            or item.lease_expires_at is None or _utc(item.lease_expires_at) <= current
        ):
            raise EdgeEventProcessingError("worker lease is stale or no longer owned")
        expiry = max(_utc(item.lease_expires_at), current + timedelta(seconds=lease_seconds))
        item.lease_expires_at = expiry
        item.updated_at = current
        db.commit()
        return expiry
    except Exception:
        db.rollback()
        raise



def complete_edge_event_transactionally(
    db: Session,
    *,
    processing_id: int,
    worker_id: str,
    fencing_token: int,
    event: dict,
    handler,
    now: datetime | None = None,
) -> None:
    """Run DB-only domain work and inbox completion in one fenced transaction.

    ``now`` is an injectable clock for deterministic tests; production callers
    should omit it so lease validity is checked against wall-clock UTC.
    """
    current = _utc(now or _now())
    try:
        item = (
            db.query(models.EdgeDeviceEventProcessing)
            .filter_by(id=processing_id)
            .with_for_update()
            .first()
        )
        if (
            item is None or item.status != "PROCESSING"
            or item.lease_owner != worker_id or item.fencing_token != fencing_token
            or item.lease_expires_at is None or _utc(item.lease_expires_at) <= current
        ):
            raise EdgeEventProcessingError("worker lease is stale or no longer owned")

        handler(db, event)
        completed_at = _utc(now or _now())
        if (
            item.status != "PROCESSING" or item.lease_owner != worker_id
            or item.fencing_token != fencing_token or item.lease_expires_at is None
            or _utc(item.lease_expires_at) <= completed_at
        ):
            raise EdgeEventProcessingError("worker lease expired during transactional handler")

        item.status = "PROCESSED"
        item.lease_owner = None
        item.lease_expires_at = None
        item.processed_at = completed_at
        item.finished_at = completed_at
        item.last_error_code = None
        item.updated_at = completed_at
        db.commit()
    except Exception:
        db.rollback()
        raise


def complete_edge_event(
    db: Session,
    *,
    processing_id: int,
    worker_id: str,
    fencing_token: int,
    now: datetime | None = None,
) -> None:
    """Complete only the current, unexpired lease holder."""
    current = _utc(now or _now())
    try:
        item = (
            db.query(models.EdgeDeviceEventProcessing)
            .filter_by(id=processing_id)
            .with_for_update()
            .first()
        )
        if (
            item is None or item.status != "PROCESSING"
            or item.lease_owner != worker_id or item.fencing_token != fencing_token
            or item.lease_expires_at is None or _utc(item.lease_expires_at) <= current
        ):
            raise EdgeEventProcessingError("worker lease is stale or no longer owned")
        item.status = "PROCESSED"
        item.lease_owner = None
        item.lease_expires_at = None
        item.processed_at = current
        item.finished_at = current
        item.last_error_code = None
        item.updated_at = current
        db.commit()
    except Exception:
        db.rollback()
        raise


def fail_edge_event(
    db: Session,
    *,
    processing_id: int,
    worker_id: str,
    fencing_token: int,
    error_code: str = "WORKER_ERROR",
    retryable: bool = True,
    now: datetime | None = None,
) -> str:
    """Schedule bounded exponential retry or move the event to the dead-letter state."""
    current = _utc(now or _now())
    safe_code = error_code if re.fullmatch(r"[A-Z0-9_]{1,80}", error_code or "") else "WORKER_ERROR"
    try:
        item = (
            db.query(models.EdgeDeviceEventProcessing)
            .filter_by(id=processing_id)
            .with_for_update()
            .first()
        )
        if (
            item is None or item.status != "PROCESSING"
            or item.lease_owner != worker_id or item.fencing_token != fencing_token
            or item.lease_expires_at is None or _utc(item.lease_expires_at) <= current
        ):
            raise EdgeEventProcessingError("worker lease is stale or no longer owned")
        dead = not retryable or item.attempt_count >= item.max_attempts
        item.status = "DEAD_LETTER" if dead else "RETRY"
        item.lease_owner = None
        item.lease_expires_at = None
        item.last_error_code = safe_code
        item.finished_at = current if dead else None
        if not dead:
            delay = min(3600, 2 ** min(item.attempt_count, 11))
            item.available_at = current + timedelta(seconds=delay)
        item.updated_at = current
        db.commit()
        return item.status
    except Exception:
        db.rollback()
        raise
