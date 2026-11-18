"""Durable dataset execution jobs with short PostgreSQL leases and fencing.

This module persists and coordinates jobs; it does not execute commands,
integrate a broker, read remote artifacts or publish outputs.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.dataset_operational_eligibility import validate_internal_image_eligibility

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL = {"SUCCEEDED", "FAILED", "REVOKED", "CANCELLED"}


class DatasetJobError(ValueError):
    """Invalid dataset execution job operation."""


class DatasetJobConflict(DatasetJobError):
    """An idempotency key was reused with a different immutable request."""


class DatasetJobLeaseLost(DatasetJobError):
    """The worker no longer owns the current unexpired fencing token."""


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise DatasetJobError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _normalise_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(sources, list) or not sources:
        raise DatasetJobError("at least one internal image source is required")
    result, seen = [], set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise DatasetJobError(f"sources[{index}] must be an object")
        image_id, store_id = source.get("shelf_image_id"), source.get("store_id")
        if isinstance(image_id, bool) or not isinstance(image_id, int) or image_id <= 0:
            raise DatasetJobError(f"sources[{index}].shelf_image_id must be a positive integer")
        if isinstance(store_id, bool) or not isinstance(store_id, int) or store_id <= 0:
            raise DatasetJobError(f"sources[{index}].store_id must be a positive integer")
        if image_id in seen:
            raise DatasetJobError(f"duplicate shelf_image_id in sources: {image_id}")
        seen.add(image_id)
        result.append({
            "shelf_image_id": image_id,
            "store_id": store_id,
            "source_image_sha256": _digest(source.get("source_image_sha256"), "source_image_sha256"),
        })
    return sorted(result, key=lambda item: item["shelf_image_id"])


def _approval(evidence: dict[str, Any], mode: str) -> tuple[str, str]:
    if not isinstance(evidence, dict) or evidence.get("status") != "APPROVED" or evidence.get("mode") != mode:
        raise DatasetJobError("approval evidence must explicitly authorize this mode")
    return (
        _digest(evidence.get("record_sha256"), "approval record SHA-256"),
        _digest(evidence.get("gate_report_sha256"), "approval report SHA-256"),
    )


def _request_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _source_entries(rows):
    return [{
        "source_type": "internal",
        "shelf_image_id": row.shelf_image_id,
        "store_id": row.store_id,
        "source_image_sha256": row.source_image_sha256,
    } for row in rows]


def _check_sources(db: Session, job: models.DatasetExecutionJob) -> tuple[bool, list[str]]:
    rows = db.query(models.DatasetExecutionJobSource).filter_by(job_id=job.id).order_by(
        models.DatasetExecutionJobSource.shelf_image_id.asc()
    ).all()
    if not rows:
        return False, ["job has no internal image source records"]
    errors, _report = validate_internal_image_eligibility(db, _source_entries(rows))
    return not errors, errors


def _append_event(db, job, event_type, *, worker_id=None, details=None):
    last = db.query(func.max(models.DatasetExecutionJobEvent.sequence_number)).filter_by(
        job_id=job.id
    ).scalar() or 0
    db.add(models.DatasetExecutionJobEvent(
        job_id=job.id,
        sequence_number=last + 1,
        event_type=event_type,
        fencing_token=job.fencing_token,
        worker_id=worker_id,
        details=details or {},
    ))


def enqueue_dataset_job(
    db: Session, *, idempotency_key: str, release_fingerprint: str,
    approval_evidence: dict[str, Any], sources: list[dict[str, Any]],
    mode: str = "training",
) -> models.DatasetExecutionJob:
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 160:
        raise DatasetJobError("idempotency_key must contain 1 to 160 non-whitespace characters")
    if mode not in {"training", "inference"}:
        raise DatasetJobError("mode must be training or inference")
    release_digest = _digest(release_fingerprint, "release_fingerprint")
    record_digest, report_digest = _approval(approval_evidence, mode)
    normalised = _normalise_sources(sources)
    payload = {
        "release_fingerprint": release_digest,
        "approval_record_sha256": record_digest,
        "approval_report_sha256": report_digest,
        "mode": mode,
        "sources": normalised,
    }
    request_digest = _request_digest(payload)
    key = idempotency_key.strip()
    existing = db.query(models.DatasetExecutionJob).filter_by(
        idempotency_key=key
    ).with_for_update().first()
    if existing is not None:
        if existing.request_sha256 != request_digest:
            raise DatasetJobConflict("idempotency_key belongs to a different immutable request")
        return existing

    errors, _report = validate_internal_image_eligibility(db, [
        {"source_type": "internal", **item} for item in normalised
    ])
    if errors:
        raise DatasetJobError("dataset source eligibility rejected: " + "; ".join(errors))

    job = models.DatasetExecutionJob(
        idempotency_key=key, request_sha256=request_digest,
        release_fingerprint=release_digest, approval_record_sha256=record_digest,
        approval_report_sha256=report_digest, mode=mode, status="QUEUED",
    )
    db.add(job)
    try:
        db.flush()
        db.add_all([models.DatasetExecutionJobSource(job_id=job.id, **item) for item in normalised])
        _append_event(db, job, "QUEUED", details={"source_count": len(normalised)})
        db.commit()
        db.refresh(job)
        return job
    except IntegrityError:
        db.rollback()
        existing = db.query(models.DatasetExecutionJob).filter_by(idempotency_key=key).first()
        if existing is not None and existing.request_sha256 == request_digest:
            return existing
        if existing is not None:
            raise DatasetJobConflict("idempotency_key was concurrently used for a different request")
        raise


def _worker(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 160:
        raise DatasetJobError("worker_id must contain 1 to 160 non-whitespace characters")
    return value.strip()


def _lease_seconds(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 86400:
        raise DatasetJobError("lease_seconds must be between 1 and 86400")
    return value


def claim_next_dataset_job(db: Session, *, worker_id: str, lease_seconds: int = 300):
    owner, duration = _worker(worker_id), _lease_seconds(lease_seconds)
    while True:
        now = models.utc_now()
        job = db.query(models.DatasetExecutionJob).filter(or_(
            models.DatasetExecutionJob.status == "QUEUED",
            (models.DatasetExecutionJob.status == "LEASED") &
            (models.DatasetExecutionJob.lease_expires_at <= now),
        )).order_by(
            models.DatasetExecutionJob.created_at.asc(),
            models.DatasetExecutionJob.id.asc(),
        ).with_for_update(skip_locked=True).first()
        if job is None:
            db.rollback()
            return None
        eligible, errors = _check_sources(db, job)
        if not eligible:
            job.status = "REVOKED"
            job.lease_owner = None
            job.lease_expires_at = None
            job.failure_code = "SOURCE_INELIGIBLE"
            job.finished_at = now
            job.updated_at = now
            _append_event(db, job, "REVOKED", details={"reasons": errors[:20]})
            db.commit()
            continue
        job.status = "LEASED"
        job.lease_owner = owner
        current_expiry = _utc(job.lease_expires_at)
        job.lease_expires_at = max(current_expiry, now + timedelta(seconds=duration))
        job.fencing_token += 1
        job.attempt_count += 1
        job.updated_at = now
        _append_event(db, job, "CLAIMED", worker_id=owner, details={"lease_seconds": duration})
        db.commit()
        db.refresh(job)
        return job


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _owned_lease(db, *, job_id, worker_id, fencing_token):
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
        raise DatasetJobError("job_id must be a positive integer")
    if isinstance(fencing_token, bool) or not isinstance(fencing_token, int) or fencing_token <= 0:
        raise DatasetJobError("fencing_token must be a positive integer")
    job = db.query(models.DatasetExecutionJob).filter_by(id=job_id).with_for_update().first()
    now = models.utc_now()
    if (job is None or job.status != "LEASED" or job.lease_owner != _worker(worker_id)
        or job.fencing_token != fencing_token or job.lease_expires_at is None
        or _utc(job.lease_expires_at) <= now):
        db.rollback()
        raise DatasetJobLeaseLost("dataset execution lease is no longer owned by this worker")
    return job


def _revoke_if_sources_invalid(db, job, worker_id):
    eligible, errors = _check_sources(db, job)
    if eligible:
        return False
    now = models.utc_now()
    job.status = "REVOKED"
    job.lease_owner = None
    job.lease_expires_at = None
    job.failure_code = "SOURCE_INELIGIBLE"
    job.finished_at = now
    job.updated_at = now
    _append_event(db, job, "REVOKED", worker_id=worker_id, details={"reasons": errors[:20]})
    return True


def heartbeat_dataset_job(db, *, job_id, worker_id, fencing_token, lease_seconds=300):
    duration = _lease_seconds(lease_seconds)
    owner = _worker(worker_id)
    job = _owned_lease(db, job_id=job_id, worker_id=owner, fencing_token=fencing_token)
    now = models.utc_now()
    if not _revoke_if_sources_invalid(db, job, owner):
        job.lease_expires_at = now + timedelta(seconds=duration)
        job.updated_at = now
        _append_event(db, job, "HEARTBEAT", worker_id=owner, details={"lease_seconds": duration})
    db.commit()
    db.refresh(job)
    return job


def complete_dataset_job(
    db, *, job_id, worker_id, fencing_token, output_sha256, staged_output_reference
):
    owner = _worker(worker_id)
    digest = _digest(output_sha256, "output_sha256")
    if (not isinstance(staged_output_reference, str)
        or not re.fullmatch(r"staging/[A-Za-z0-9._/-]{1,590}", staged_output_reference)
        or ".." in staged_output_reference.split("/")):
        raise DatasetJobError("staged_output_reference must be a safe staging-relative reference")
    job = _owned_lease(db, job_id=job_id, worker_id=owner, fencing_token=fencing_token)
    now = models.utc_now()
    if not _revoke_if_sources_invalid(db, job, owner):
        job.status = "SUCCEEDED"
        job.lease_owner = None
        job.lease_expires_at = None
        job.output_sha256 = digest
        job.staged_output_reference = staged_output_reference
        job.finished_at = now
        job.updated_at = now
        _append_event(db, job, "SUCCEEDED", worker_id=owner, details={"output_sha256": digest})
    db.commit()
    db.refresh(job)
    return job


def fail_dataset_job(db, *, job_id, worker_id, fencing_token, failure_code):
    owner = _worker(worker_id)
    if not isinstance(failure_code, str) or not re.fullmatch(r"[A-Z0-9_]{1,80}", failure_code):
        raise DatasetJobError("failure_code must be a short uppercase identifier")
    job = _owned_lease(db, job_id=job_id, worker_id=owner, fencing_token=fencing_token)
    now = models.utc_now()
    job.status = "FAILED"
    job.lease_owner = None
    job.lease_expires_at = None
    job.failure_code = failure_code
    job.finished_at = now
    job.updated_at = now
    _append_event(db, job, "FAILED", worker_id=owner, details={"failure_code": failure_code})
    db.commit()
    db.refresh(job)
    return job
