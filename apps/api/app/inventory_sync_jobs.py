"""Durable queue and fencing primitives for ERP/WMS synchronization."""
from __future__ import annotations
from datetime import timedelta, timezone
from uuid import uuid4
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app import models


class InventorySyncJobError(ValueError):
    pass


class InventorySyncJobConflict(InventorySyncJobError):
    pass


class InventorySyncJobNotConfigured(InventorySyncJobError):
    pass


class InventorySyncJobLeaseLost(InventorySyncJobError):
    pass


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _worker(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 160:
        raise InventorySyncJobError("worker_id must contain 1 to 160 non-whitespace characters")
    return value.strip()


def _lease_seconds(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 30 <= value <= 3600:
        raise InventorySyncJobError("lease_seconds must be between 30 and 3600")
    return value


def _event(db, job, kind, worker=None, details=None):
    sequence = db.query(func.max(models.InventorySyncJobEvent.sequence_number)).filter_by(job_id=job.id).scalar() or 0
    db.add(models.InventorySyncJobEvent(
        job_id=job.id, sequence_number=sequence + 1, event_type=kind,
        worker_id=worker, fencing_token=job.fencing_token,
        details=details or {}, created_at=models.utc_now(),
    ))
    db.flush()


def enqueue_inventory_sync_job(db: Session, *, store_id: int, source: str, provider: str,
                               idempotency_key: str, requested_by_user_id: int,
                               scheduled_at=None, max_attempts: int = 3):
    provider = provider.strip() if isinstance(provider, str) else ""
    key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
    if source not in {"ERP", "WMS"} or not provider or len(provider) > 120 or not key or len(key) > 160:
        raise InventorySyncJobError("source, provider or idempotency_key is invalid")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 10:
        raise InventorySyncJobError("max_attempts must be between 1 and 10")
    when = scheduled_at or models.utc_now()
    if when.tzinfo is None or when.utcoffset() is None:
        raise InventorySyncJobError("scheduled_at must include a timezone")
    if db.get(models.Store, store_id) is None or db.get(models.User, requested_by_user_id) is None:
        raise InventorySyncJobError("store or requesting user does not exist")
    existing = db.query(models.InventorySyncJob).filter_by(
        store_id=store_id, source=source, idempotency_key=key
    ).first()
    if existing is not None:
        if existing.provider != provider:
            raise InventorySyncJobConflict("idempotency_key belongs to a different provider")
        return existing
    integration = db.query(models.StoreExternalIntegration).filter_by(
        store_id=store_id, external_system=source, provider=provider, status="ACTIVE"
    ).first()
    if integration is None:
        raise InventorySyncJobNotConfigured("No active store integration matches this provider")
    now = models.utc_now()
    job = models.InventorySyncJob(
        store_id=store_id, source=source, provider=provider, idempotency_key=key,
        requested_by_user_id=requested_by_user_id, status="QUEUED",
        attempt_count=0, max_attempts=max_attempts, scheduled_at=when,
        created_at=now, updated_at=now,
    )
    db.add(job)
    try:
        db.flush()
        _event(db, job, "QUEUED", details={"source": source, "provider": provider})
        db.commit()
        db.refresh(job)
        return job
    except IntegrityError:
        db.rollback()
        existing = db.query(models.InventorySyncJob).filter_by(
            store_id=store_id, source=source, idempotency_key=key
        ).first()
        if existing is not None and existing.provider == provider:
            return existing
        raise InventorySyncJobConflict("idempotency_key was concurrently reused")


def claim_next_inventory_sync_job(db: Session, *, worker_id: str, lease_seconds: int = 300):
    owner, duration = _worker(worker_id), _lease_seconds(lease_seconds)
    while True:
        now = models.utc_now()
        job = db.query(models.InventorySyncJob).filter(or_(
            (models.InventorySyncJob.status == "QUEUED") & (models.InventorySyncJob.scheduled_at <= now),
            (models.InventorySyncJob.status == "RUNNING") & (models.InventorySyncJob.lease_expires_at <= now),
        )).order_by(
            models.InventorySyncJob.scheduled_at, models.InventorySyncJob.created_at,
            models.InventorySyncJob.id,
        ).with_for_update(skip_locked=True).first()
        if job is None:
            db.rollback()
            return None
        expired = job.status == "RUNNING"
        if expired:
            _event(db, job, "LEASE_EXPIRED", owner, {
                "previous_worker": job.lease_owner, "previous_fencing_token": job.fencing_token,
            })
            if job.attempt_count >= job.max_attempts:
                sync = db.get(models.InventorySourceSync, job.latest_sync_id) if job.latest_sync_id else None
                job.status = "PARTIAL" if sync is not None and sync.status == "PARTIAL" else "FAILED"
                job.finished_at = now
                job.error_code = "LEASE_EXHAUSTED"
                job.error_message = "Worker lease expired after the maximum number of attempts."
                job.lease_owner = job.lease_token = job.lease_expires_at = None
                job.updated_at = now
                _event(db, job, job.status, owner, {"reason": "maximum attempts exhausted"})
                db.commit()
                continue
        job.status = "RUNNING"
        job.lease_owner = owner
        job.lease_token = str(uuid4())
        job.fencing_token += 1
        job.attempt_count += 1
        job.lease_expires_at = now + timedelta(seconds=duration)
        job.started_at = now
        job.finished_at = None
        job.error_code = job.error_message = None
        job.updated_at = now
        _event(db, job, "CLAIMED", owner, {
            "attempt": job.attempt_count, "max_attempts": job.max_attempts,
            "lease_seconds": duration, "recovered_expired_lease": expired,
        })
        db.commit()
        db.refresh(job)
        return job


def _owned(db, *, job_id, worker_id, lease_token, fencing_token):
    job = db.query(models.InventorySyncJob).filter_by(id=job_id).with_for_update().first()
    now = models.utc_now()
    if (job is None or job.status != "RUNNING" or job.lease_owner != _worker(worker_id)
        or job.lease_token != lease_token or job.fencing_token != fencing_token
        or job.lease_expires_at is None or _utc(job.lease_expires_at) <= now):
        db.rollback()
        raise InventorySyncJobLeaseLost("inventory synchronization lease is no longer owned by this worker")
    return job


def assert_and_renew_inventory_sync_job_lease(db: Session, *, job_id: int, worker_id: str,
        lease_token: str, fencing_token: int, lease_seconds: int = 300):
    duration = _lease_seconds(lease_seconds)
    job = _owned(db, job_id=job_id, worker_id=worker_id, lease_token=lease_token, fencing_token=fencing_token)
    now = models.utc_now()
    job.lease_expires_at = max(_utc(job.lease_expires_at), now + timedelta(seconds=duration))
    job.updated_at = now
    return job


def heartbeat_inventory_sync_job(db: Session, *, job_id: int, worker_id: str,
        lease_token: str, fencing_token: int, lease_seconds: int = 300):
    job = assert_and_renew_inventory_sync_job_lease(
        db, job_id=job_id, worker_id=worker_id, lease_token=lease_token,
        fencing_token=fencing_token, lease_seconds=lease_seconds,
    )
    _event(db, job, "HEARTBEAT", worker_id, {"lease_seconds": lease_seconds})
    db.commit()
    db.refresh(job)
    return job


def complete_inventory_sync_job(db: Session, *, job_id: int, worker_id: str,
        lease_token: str, fencing_token: int, status: str, sync_id: int | None = None):
    if status not in {"SUCCEEDED", "PARTIAL"}:
        raise InventorySyncJobError("completion status must be SUCCEEDED or PARTIAL")
    job = _owned(db, job_id=job_id, worker_id=worker_id, lease_token=lease_token, fencing_token=fencing_token)
    job.status = status
    job.latest_sync_id = sync_id or job.latest_sync_id
    job.finished_at = models.utc_now()
    job.lease_owner = job.lease_token = job.lease_expires_at = None
    job.updated_at = models.utc_now()
    _event(db, job, status, worker_id, {"sync_id": job.latest_sync_id})
    db.commit()
    db.refresh(job)
    return job


def fail_or_retry_inventory_sync_job(db: Session, *, job_id: int, worker_id: str,
        lease_token: str, fencing_token: int, error_code: str = "SYNC_EXECUTION_FAILED"):
    if not isinstance(error_code, str) or not error_code.replace("_", "").isalnum() or len(error_code) > 80:
        raise InventorySyncJobError("error_code must be a short alphanumeric identifier")
    job = _owned(db, job_id=job_id, worker_id=worker_id, lease_token=lease_token, fencing_token=fencing_token)
    now = models.utc_now()
    job.error_code = error_code.upper()
    job.error_message = "The synchronization attempt failed. Consult the sanitized job event and source-sync ledger."
    job.lease_owner = job.lease_token = job.lease_expires_at = None
    job.updated_at = now
    sync = db.get(models.InventorySourceSync, job.latest_sync_id) if job.latest_sync_id else None
    if job.attempt_count < job.max_attempts:
        delay = min(900, 15 * (2 ** max(0, job.attempt_count - 1)))
        job.status = "QUEUED"
        job.scheduled_at = now + timedelta(seconds=delay)
        job.finished_at = None
        _event(db, job, "RETRY_SCHEDULED", worker_id, {
            "attempt": job.attempt_count, "next_attempt_in_seconds": delay, "error_code": job.error_code,
        })
    else:
        job.status = "PARTIAL" if sync is not None and sync.status == "PARTIAL" else "FAILED"
        job.finished_at = now
        _event(db, job, job.status, worker_id, {"error_code": job.error_code})
    db.commit()
    db.refresh(job)
    return job
