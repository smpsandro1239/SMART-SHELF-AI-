"""Individual credentials and scope authorization for dataset worker identities.

Credentials are high-entropy bearer secrets. Only SHA-256 digests are persisted;
the plaintext is returned once by the trusted provisioning interface.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import models

DATASET_WORKER_SCOPES = frozenset({
    "jobs:claim",
    "jobs:heartbeat",
    "jobs:complete",
    "jobs:fail",
    "artifacts:read",
    "outputs:publish",
})
_MIN_CREDENTIAL_LIFETIME_SECONDS = 60
_MAX_CREDENTIAL_LIFETIME_SECONDS = 90 * 24 * 60 * 60
_WORKER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_CREDENTIAL = re.compile(r"^ssw1\.([0-9a-f]{32})\.([A-Za-z0-9_-]{40,64})$")


class DatasetWorkerCredentialError(ValueError):
    """Invalid worker credential management operation."""


class DatasetWorkerAuthenticationError(PermissionError):
    """Worker credential is invalid, expired, revoked or disabled."""


class DatasetWorkerAuthorizationError(PermissionError):
    """Authenticated worker lacks the required operation scope."""


@dataclass(frozen=True)
class DatasetWorkerPrincipal:
    worker_id: str
    credential_id: str
    scopes: frozenset[str]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _normalise_worker_id(value: str) -> str:
    if not isinstance(value, str) or not _WORKER_ID.fullmatch(value):
        raise DatasetWorkerCredentialError("worker_id must be a stable 1-160 character identifier")
    return value


def _normalise_scopes(scopes: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    if isinstance(scopes, (str, bytes)) or not isinstance(scopes, (list, tuple, set)):
        raise DatasetWorkerCredentialError("scopes must be a collection of explicit scope names")
    values = list(scopes)
    if not values or any(not isinstance(scope, str) for scope in values):
        raise DatasetWorkerCredentialError("at least one valid worker scope is required")
    if len(values) != len(set(values)):
        raise DatasetWorkerCredentialError("duplicate worker scopes are not allowed")
    unknown = sorted(set(values) - DATASET_WORKER_SCOPES)
    if unknown:
        raise DatasetWorkerCredentialError("unsupported worker scopes: " + ", ".join(unknown))
    return sorted(values)


def _record_event(db: Session, worker_id: str, event_type: str, credential_id: str | None, **details) -> None:
    db.add(models.DatasetWorkerEvent(
        worker_id=worker_id,
        credential_id=credential_id,
        event_type=event_type,
        details=details,
    ))


def issue_dataset_worker_credential(
    db: Session,
    *,
    worker_id: str,
    scopes: list[str] | tuple[str, ...] | set[str],
    expires_in_seconds: int = 30 * 24 * 60 * 60,
    rotate: bool = False,
) -> tuple[str, models.DatasetWorkerCredential]:
    """Register a worker if needed and issue a one-time credential.

    Rotation revokes every currently active credential in the same transaction.
    This function is intended for trusted local/administrative provisioning only.
    """
    identity = _normalise_worker_id(worker_id)
    granted_scopes = _normalise_scopes(scopes)
    if (
        isinstance(expires_in_seconds, bool)
        or not isinstance(expires_in_seconds, int)
        or not _MIN_CREDENTIAL_LIFETIME_SECONDS <= expires_in_seconds <= _MAX_CREDENTIAL_LIFETIME_SECONDS
    ):
        raise DatasetWorkerCredentialError("credential lifetime must be between 60 seconds and 90 days")

    try:
        worker = db.query(models.DatasetWorker).filter_by(worker_id=identity).with_for_update().first()
        now = _now()
        if worker is None:
            worker = models.DatasetWorker(worker_id=identity, status="ACTIVE", created_at=now)
            db.add(worker)
            db.flush()
            _record_event(db, identity, "WORKER_REGISTERED", None)
        elif worker.status != "ACTIVE":
            raise DatasetWorkerCredentialError("disabled workers cannot receive credentials")

        active = db.query(models.DatasetWorkerCredential).filter(
            models.DatasetWorkerCredential.worker_id == identity,
            models.DatasetWorkerCredential.revoked_at.is_(None),
            models.DatasetWorkerCredential.expires_at > now,
        ).with_for_update().all()
        if active and not rotate:
            raise DatasetWorkerCredentialError("worker already has an active credential; use rotation")

        credential_id = secrets.token_hex(16)
        secret = secrets.token_urlsafe(32)
        plaintext = f"ssw1.{credential_id}.{secret}"
        credential = models.DatasetWorkerCredential(
            credential_id=credential_id,
            worker_id=identity,
            secret_sha256=hashlib.sha256(secret.encode("ascii")).hexdigest(),
            scopes=granted_scopes,
            created_at=now,
            expires_at=now + timedelta(seconds=expires_in_seconds),
        )
        db.add(credential)
        db.flush()

        if active:
            for previous in active:
                previous.revoked_at = now
                previous.replaced_by_credential_id = credential_id
            event_type = "CREDENTIAL_ROTATED"
        else:
            event_type = "CREDENTIAL_ISSUED"
        _record_event(
            db, identity, event_type, credential_id,
            scopes=granted_scopes, expires_at=credential.expires_at.isoformat(),
            replaced_count=len(active),
        )
        db.commit()
        db.refresh(credential)
        return plaintext, credential
    except Exception:
        db.rollback()
        raise


def revoke_dataset_worker_credential(
    db: Session, *, credential_id: str
) -> bool:
    if not isinstance(credential_id, str) or not re.fullmatch(r"[0-9a-f]{32}", credential_id):
        raise DatasetWorkerCredentialError("credential_id is invalid")
    try:
        credential = db.query(models.DatasetWorkerCredential).filter_by(
            credential_id=credential_id
        ).with_for_update().first()
        if credential is None or credential.revoked_at is not None:
            db.rollback()
            return False
        now = _now()
        credential.revoked_at = now
        _record_event(db, credential.worker_id, "CREDENTIAL_REVOKED", credential_id)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def disable_dataset_worker(db: Session, *, worker_id: str) -> bool:
    identity = _normalise_worker_id(worker_id)
    try:
        worker = db.query(models.DatasetWorker).filter_by(worker_id=identity).with_for_update().first()
        if worker is None or worker.status == "DISABLED":
            db.rollback()
            return False
        now = _now()
        worker.status = "DISABLED"
        worker.disabled_at = now
        db.query(models.DatasetWorkerCredential).filter(
            models.DatasetWorkerCredential.worker_id == identity,
            models.DatasetWorkerCredential.revoked_at.is_(None),
        ).update({models.DatasetWorkerCredential.revoked_at: now}, synchronize_session=False)
        _record_event(db, identity, "WORKER_DISABLED", None)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def authenticate_dataset_worker(db: Session, *, bearer_token: str) -> DatasetWorkerPrincipal:
    """Authenticate a worker token; caller owns the surrounding DB transaction."""
    if not isinstance(bearer_token, str):
        raise DatasetWorkerAuthenticationError("invalid worker credential")
    match = _CREDENTIAL.fullmatch(bearer_token)
    if match is None:
        raise DatasetWorkerAuthenticationError("invalid worker credential")
    credential_id, supplied_secret = match.groups()
    credential = db.query(models.DatasetWorkerCredential).filter_by(
        credential_id=credential_id
    ).first()
    supplied_digest = hashlib.sha256(supplied_secret.encode("ascii")).hexdigest()
    expected_digest = credential.secret_sha256 if credential is not None else "0" * 64
    digest_matches = hmac.compare_digest(supplied_digest, expected_digest)
    now = _now()
    if (
        credential is None
        or not digest_matches
        or credential.revoked_at is not None
        or _utc(credential.expires_at) <= now
        or credential.worker.status != "ACTIVE"
    ):
        raise DatasetWorkerAuthenticationError("invalid worker credential")
    credential.last_used_at = now
    db.flush()
    return DatasetWorkerPrincipal(
        worker_id=credential.worker_id,
        credential_id=credential.credential_id,
        scopes=frozenset(credential.scopes),
    )


def require_dataset_worker_scope(
    principal: DatasetWorkerPrincipal, *, required_scope: str
) -> None:
    if required_scope not in DATASET_WORKER_SCOPES:
        raise DatasetWorkerAuthorizationError("unknown worker operation scope")
    if required_scope not in principal.scopes:
        raise DatasetWorkerAuthorizationError("worker credential lacks the required scope")
