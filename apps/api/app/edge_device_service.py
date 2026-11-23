"""Trusted provisioning and signed, replay-resistant Edge device event ingestion.

Provisioning functions are intended for an authenticated administrative workflow or
a controlled CLI. No public registration endpoint is exposed by this module.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.edge_event_contract import (
    EdgeEventContractError,
    EdgeEventEnvelope,
    canonical_event_bytes,
    classify_sequence,
    event_fingerprint,
    verify_idempotent_replay,
)

EDGE_DEVICE_TYPES = frozenset({"fixed_camera", "robot", "mobile", "gateway"})
EDGE_DEVICE_SCOPES = frozenset({"events:write"})
_CREDENTIAL = re.compile(r"^sse1\.([0-9a-f]{32})\.([A-Za-z0-9_-]{40,64})$")
_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{22,128}$")
_SIGNATURE = re.compile(r"^[0-9a-f]{64}$")
_MAX_LIFETIME = 90 * 24 * 60 * 60
_CLOCK_SKEW = 300
_NONCE_TTL = 600


class EdgeDeviceError(ValueError):
    """Invalid edge device provisioning or event operation."""


class EdgeDeviceAuthenticationError(PermissionError):
    """Device credential or signed request is invalid."""


class EdgeDeviceAuthorizationError(PermissionError):
    """Device lacks the required capability or tenant binding."""


class EdgeDeviceReplayError(PermissionError):
    """A signed request nonce or event sequence has already been used."""


@dataclass(frozen=True)
class EdgeDevicePrincipal:
    device_id: str
    store_id: int
    credential_id: str
    scopes: frozenset[str]


@dataclass(frozen=True)
class EdgeIngestResult:
    event_id: str
    device_id: str
    sequence_number: int
    disposition: str
    duplicate: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _record_audit(db: Session, *, device_id: str, event_type: str, credential_id: str | None = None, **details) -> None:
    db.add(models.EdgeDeviceAuditEvent(
        device_id=device_id,
        credential_id=credential_id,
        event_type=event_type,
        details=details,
        created_at=_now(),
    ))


def register_edge_device(
    db: Session, *, device_id: str, store_id: int, device_type: str
) -> models.EdgeDevice:
    """Register a store-bound device. This function must only be called by trusted admin code."""
    if not isinstance(device_id, str) or not _DEVICE_ID.fullmatch(device_id):
        raise EdgeDeviceError("device_id must be a stable 1-120 character identifier")
    if type(store_id) is not int or store_id <= 0:
        raise EdgeDeviceError("store_id must be a positive integer")
    if device_type not in EDGE_DEVICE_TYPES:
        raise EdgeDeviceError("unsupported edge device type")
    if db.query(models.Store.id).filter(models.Store.id == store_id).first() is None:
        raise EdgeDeviceError("store does not exist")
    if db.query(models.EdgeDevice).filter_by(device_id=device_id).first() is not None:
        raise EdgeDeviceError("device_id is already registered")
    device = models.EdgeDevice(
        device_id=device_id, store_id=store_id, device_type=device_type,
        status="ACTIVE", created_at=_now(),
    )
    try:
        db.add(device)
        _record_audit(db, device_id=device_id, event_type="DEVICE_REGISTERED", store_id=store_id, device_type=device_type)
        db.commit()
        db.refresh(device)
        return device
    except IntegrityError as exc:
        db.rollback()
        raise EdgeDeviceError("device_id is already registered or store is invalid") from exc
    except Exception:
        db.rollback()
        raise


def issue_edge_device_credential(
    db: Session, *, device_id: str, scopes: list[str] | tuple[str, ...] = ("events:write",),
    expires_in_seconds: int = 30 * 24 * 60 * 60, rotate: bool = False,
) -> tuple[str, models.EdgeDeviceCredential]:
    """Issue a one-time bearer secret; only its SHA-256 digest is persisted."""
    if not isinstance(device_id, str) or not _DEVICE_ID.fullmatch(device_id):
        raise EdgeDeviceError("device_id is invalid")
    if isinstance(scopes, (str, bytes)) or not isinstance(scopes, (list, tuple, set)):
        raise EdgeDeviceError("scopes must be a collection")
    scope_values = list(scopes)
    if not scope_values or len(scope_values) != len(set(scope_values)) or set(scope_values) - EDGE_DEVICE_SCOPES:
        raise EdgeDeviceError("unsupported or duplicate device scopes")
    if isinstance(expires_in_seconds, bool) or not isinstance(expires_in_seconds, int) or not 60 <= expires_in_seconds <= _MAX_LIFETIME:
        raise EdgeDeviceError("credential lifetime must be between 60 seconds and 90 days")
    try:
        device = db.query(models.EdgeDevice).filter_by(device_id=device_id).with_for_update().first()
        if device is None or device.status != "ACTIVE":
            raise EdgeDeviceError("device is missing or disabled")
        now = _now()
        active = db.query(models.EdgeDeviceCredential).filter(
            models.EdgeDeviceCredential.device_id == device_id,
            models.EdgeDeviceCredential.revoked_at.is_(None),
            models.EdgeDeviceCredential.expires_at > now,
        ).with_for_update().all()
        if active and not rotate:
            raise EdgeDeviceError("device already has an active credential; use rotation")
        credential_id = secrets.token_hex(16)
        secret = secrets.token_urlsafe(32)
        token = f"sse1.{credential_id}.{secret}"
        credential = models.EdgeDeviceCredential(
            credential_id=credential_id,
            device_id=device_id,
            secret_sha256=hashlib.sha256(secret.encode("ascii")).hexdigest(),
            scopes=sorted(scope_values),
            created_at=now,
            expires_at=now + timedelta(seconds=expires_in_seconds),
        )
        db.add(credential)
        db.flush()
        for previous in active:
            previous.revoked_at = now
            previous.replaced_by_credential_id = credential_id
        _record_audit(
            db, device_id=device_id,
            event_type="CREDENTIAL_ROTATED" if active else "CREDENTIAL_ISSUED",
            credential_id=credential_id, scopes=sorted(scope_values), replaced_count=len(active),
            expires_at=credential.expires_at.isoformat(),
        )
        db.commit()
        db.refresh(credential)
        return token, credential
    except Exception:
        db.rollback()
        raise


def revoke_edge_device_credential(db: Session, *, credential_id: str) -> bool:
    if not isinstance(credential_id, str) or not re.fullmatch(r"[0-9a-f]{32}", credential_id):
        raise EdgeDeviceError("credential_id is invalid")
    try:
        credential = db.query(models.EdgeDeviceCredential).filter_by(
            credential_id=credential_id
        ).with_for_update().first()
        if credential is None or credential.revoked_at is not None:
            db.rollback()
            return False
        credential.revoked_at = _now()
        _record_audit(
            db, device_id=credential.device_id, event_type="CREDENTIAL_REVOKED",
            credential_id=credential_id,
        )
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def disable_edge_device(db: Session, *, device_id: str) -> bool:
    try:
        device = db.query(models.EdgeDevice).filter_by(device_id=device_id).with_for_update().first()
        if device is None or device.status == "DISABLED":
            db.rollback()
            return False
        now = _now()
        device.status = "DISABLED"
        device.disabled_at = now
        db.query(models.EdgeDeviceCredential).filter(
            models.EdgeDeviceCredential.device_id == device_id,
            models.EdgeDeviceCredential.revoked_at.is_(None),
        ).update({models.EdgeDeviceCredential.revoked_at: now}, synchronize_session=False)
        _record_audit(db, device_id=device_id, event_type="DEVICE_DISABLED")
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


def _canonical_signed_request(*, credential_id: str, method: str, request_target: str,
                              timestamp: int, nonce: str, body: bytes) -> bytes:
    if not isinstance(method, str) or not re.fullmatch(r"[A-Z]{3,10}", method):
        raise EdgeDeviceAuthenticationError("invalid signed request")
    if not isinstance(request_target, str) or not request_target.startswith("/") or "\n" in request_target:
        raise EdgeDeviceAuthenticationError("invalid signed request")
    if not isinstance(body, bytes) or len(body) > 128 * 1024:
        raise EdgeDeviceAuthenticationError("invalid signed request")
    return "\n".join((
        "SMART-SHELF-EDGE-V1", credential_id, method, request_target,
        str(timestamp), nonce, hashlib.sha256(body).hexdigest(),
    )).encode("utf-8")


def sign_edge_device_request(*, bearer_token: str, method: str, request_target: str,
                             timestamp: int, nonce: str, body: bytes) -> str:
    """Helper for trusted device SDKs and deterministic tests; never logs the token."""
    match = _CREDENTIAL.fullmatch(bearer_token) if isinstance(bearer_token, str) else None
    if match is None or not _NONCE.fullmatch(nonce or ""):
        raise EdgeDeviceAuthenticationError("invalid signing input")
    credential_id, secret = match.groups()
    key = hmac.new(secret.encode("ascii"), b"SMART-SHELF-EDGE-HMAC-SHA256-V1", hashlib.sha256).digest()
    canonical = _canonical_signed_request(
        credential_id=credential_id, method=method, request_target=request_target,
        timestamp=timestamp, nonce=nonce, body=body,
    )
    return hmac.new(key, canonical, hashlib.sha256).hexdigest()


def authenticate_edge_device_request(
    db: Session, *, bearer_token: str, method: str, request_target: str,
    timestamp: int, nonce: str, signature: str, body: bytes,
    required_scope: str = "events:write", now: datetime | None = None,
) -> EdgeDevicePrincipal:
    """Authenticate, authorise and atomically consume the signed request nonce."""
    current = _utc(now or _now())
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
        raise EdgeDeviceAuthenticationError("invalid signed request")
    if abs(current.timestamp() - timestamp) > _CLOCK_SKEW:
        raise EdgeDeviceAuthenticationError("signed request timestamp is outside the accepted window")
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise EdgeDeviceAuthenticationError("invalid signed request")
    if not isinstance(signature, str) or not _SIGNATURE.fullmatch(signature):
        raise EdgeDeviceAuthenticationError("invalid signed request")
    match = _CREDENTIAL.fullmatch(bearer_token) if isinstance(bearer_token, str) else None
    if match is None:
        raise EdgeDeviceAuthenticationError("invalid device credential")
    credential_id, supplied_secret = match.groups()
    credential = db.query(models.EdgeDeviceCredential).filter_by(credential_id=credential_id).first()
    if credential is None:
        raise EdgeDeviceAuthenticationError("invalid device credential")
    device = db.query(models.EdgeDevice).filter_by(
        device_id=credential.device_id
    ).with_for_update(read=True).populate_existing().first()
    credential = db.query(models.EdgeDeviceCredential).filter_by(
        credential_id=credential_id
    ).with_for_update().populate_existing().first()
    supplied_digest = hashlib.sha256(supplied_secret.encode("ascii")).hexdigest()
    digest_matches = hmac.compare_digest(supplied_digest, credential.secret_sha256 if credential else "0" * 64)
    if (
        not digest_matches or device is None or credential is None
        or device.status != "ACTIVE" or credential.revoked_at is not None
        or _utc(credential.expires_at) <= current
    ):
        raise EdgeDeviceAuthenticationError("invalid device credential")
    scopes = frozenset(credential.scopes or [])
    if required_scope not in EDGE_DEVICE_SCOPES or required_scope not in scopes:
        raise EdgeDeviceAuthorizationError("device credential lacks the required scope")
    canonical = _canonical_signed_request(
        credential_id=credential_id, method=method, request_target=request_target,
        timestamp=timestamp, nonce=nonce, body=body,
    )
    # Use domain-separated HMAC key derivation. The persisted SHA-256 verifier is not a signing key.
    signing_key = hmac.new(
        supplied_secret.encode("ascii"), b"SMART-SHELF-EDGE-HMAC-SHA256-V1", hashlib.sha256
    ).digest()
    expected = hmac.new(signing_key, canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise EdgeDeviceAuthenticationError("invalid signed request")
    try:
        db.query(models.EdgeDeviceRequestNonce).filter(
            models.EdgeDeviceRequestNonce.expires_at <= current
        ).delete(synchronize_session=False)
        db.add(models.EdgeDeviceRequestNonce(
            credential_id=credential_id,
            nonce_sha256=hashlib.sha256(nonce.encode("ascii")).hexdigest(),
            request_timestamp=timestamp,
            expires_at=current + timedelta(seconds=_NONCE_TTL),
            created_at=current,
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise EdgeDeviceReplayError("signed request nonce has already been used") from exc
    except Exception:
        db.rollback()
        raise
    return EdgeDevicePrincipal(
        device_id=device.device_id, store_id=device.store_id,
        credential_id=credential_id, scopes=scopes,
    )


def ingest_edge_event(
    db: Session, *, principal: EdgeDevicePrincipal, event: EdgeEventEnvelope,
    now: datetime | None = None,
) -> EdgeIngestResult:
    """Persist an authenticated event and advance its sequence cursor atomically."""
    if event.device_id != principal.device_id or event.store_id != principal.store_id:
        raise EdgeDeviceAuthorizationError("event identity does not match authenticated device")
    current = _utc(now or _now())
    try:
        device = db.query(models.EdgeDevice).filter_by(
            device_id=principal.device_id
        ).with_for_update().populate_existing().first()
        credential = db.query(models.EdgeDeviceCredential).filter_by(
            credential_id=principal.credential_id, device_id=principal.device_id
        ).with_for_update(read=True).populate_existing().first()
        if (
            device is None or device.status != "ACTIVE" or device.store_id != principal.store_id
            or credential is None or credential.revoked_at is not None
            or _utc(credential.expires_at) <= current
            or "events:write" not in (credential.scopes or [])
        ):
            raise EdgeDeviceAuthenticationError("device principal is no longer active")
        if event.shelf_id is not None:
            shelf_store_id = (
                db.query(models.Zone.store_id)
                .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
                .filter(models.Shelf.id == event.shelf_id)
                .scalar()
            )
            if shelf_store_id != device.store_id:
                raise EdgeDeviceAuthorizationError("shelf does not belong to the authenticated device store")

        fingerprint = event_fingerprint(event)
        existing = db.query(models.EdgeDeviceEventInbox).filter_by(
            device_id=device.device_id, event_id=event.event_id
        ).with_for_update().first()
        if existing is not None:
            verify_idempotent_replay(existing.fingerprint_sha256, fingerprint)
            db.rollback()
            return EdgeIngestResult(
                event_id=event.event_id, device_id=device.device_id,
                sequence_number=existing.sequence_number, disposition="DUPLICATE", duplicate=True,
            )

        cursor = db.query(models.EdgeDeviceEventCursor).filter_by(
            device_id=device.device_id
        ).with_for_update().first()
        if cursor is None:
            cursor = models.EdgeDeviceEventCursor(
                device_id=device.device_id, last_sequence=0, updated_at=current,
            )
            db.add(cursor)
            db.flush()
        disposition = classify_sequence(cursor.last_sequence, event.sequence_number)
        if disposition.value == "STALE":
            raise EdgeDeviceReplayError("event sequence is older than the accepted cursor")
        if disposition.value == "GAP":
            raise EdgeDeviceReplayError("event sequence gap detected; missing events must be delivered first")
        device.last_seen_at = current
        if event.event_type == "DEVICE_HEARTBEAT":
            if "firmware_version" in event.payload:
                device.firmware_version = event.payload["firmware_version"]
            if "network_status" in event.payload:
                device.last_network_status = event.payload["network_status"]
            if "battery_pct" in event.payload:
                device.battery_pct = float(event.payload["battery_pct"])
            if "storage_free_bytes" in event.payload:
                device.storage_free_bytes = event.payload["storage_free_bytes"]

        db.add(models.EdgeDeviceEventInbox(
            device_id=device.device_id, event_id=event.event_id,
            sequence_number=event.sequence_number, event_type=event.event_type,
            store_id=device.store_id, shelf_id=event.shelf_id,
            occurred_at=event.occurred_at, payload=event.model_dump(mode="json"),
            fingerprint_sha256=fingerprint, received_at=current,
        ))
        db.flush()
        inbox_row = db.query(models.EdgeDeviceEventInbox).filter_by(
            device_id=device.device_id, event_id=event.event_id
        ).one()
        db.add(models.EdgeDeviceEventProcessing(
            inbox_id=inbox_row.id, status="PENDING", attempt_count=0,
            max_attempts=8, available_at=current, fencing_token=0,
            created_at=current, updated_at=current,
        ))
        cursor.last_sequence = event.sequence_number
        cursor.updated_at = current
        db.commit()
        return EdgeIngestResult(
            event_id=event.event_id, device_id=device.device_id,
            sequence_number=event.sequence_number, disposition=disposition.value, duplicate=False,
        )
    except Exception:
        db.rollback()
        raise
