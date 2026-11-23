from datetime import datetime, timezone
import hashlib
import hmac
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.edge_event_contract import EdgeEventContractError, EdgeEventEnvelope
from app.edge_device_service import (
    EdgeDeviceAuthenticationError,
    EdgeDeviceAuthorizationError,
    EdgeDeviceError,
    EdgeDeviceReplayError,
    authenticate_edge_device_request,
    disable_edge_device,
    ingest_edge_event,
    issue_edge_device_credential,
    register_edge_device,
    revoke_edge_device_credential,
    sign_edge_device_request,
    _canonical_signed_request,
)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'edge-device-service.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed_store(db, code="EDGE-STORE-A"):
    store = models.Store(code=code, name=code)
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Aisle 1")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code=f"{code}-SHELF")
    db.add(shelf)
    db.commit()
    return store.id, shelf.id


def make_event(device_id, store_id, shelf_id=None, sequence=1, event_id=None):
    return EdgeEventEnvelope(
        schema_version=1,
        event_id=event_id or str(uuid4()),
        event_type="DEVICE_HEARTBEAT" if shelf_id is None else "SHELF_OBSERVATION",
        device_id=device_id,
        store_id=store_id,
        shelf_id=shelf_id,
        sequence_number=sequence,
        occurred_at=datetime.now(timezone.utc),
        payload=(
            {"firmware_version": "1.2.0", "network_status": "ONLINE"}
            if shelf_id is None else {
                "capture_id": str(uuid4()),
                "model_version": "detector-v1",
                "observations": [],
            }
        ),
    )


def signed_request(token, body, nonce, timestamp):
    signature = sign_edge_device_request(
        bearer_token=token, method="POST", request_target="/api/v1/edge/events",
        timestamp=timestamp, nonce=nonce, body=body,
    )
    return authenticate_edge_device_request(
        db=None, bearer_token=token, method="POST",
        request_target="/api/v1/edge/events", timestamp=timestamp,
        nonce=nonce, signature=signature, body=body,
    )


def test_registration_and_credential_issue_store_only_secret_digest(db):
    store_id, _ = seed_store(db)
    device = register_edge_device(
        db, device_id="camera-edge-01", store_id=store_id, device_type="fixed_camera"
    )
    token, credential = issue_edge_device_credential(db, device_id=device.device_id)

    assert device.store_id == store_id
    assert token.startswith(f"sse1.{credential.credential_id}.")
    assert credential.secret_sha256 not in token
    assert len(credential.secret_sha256) == 64
    assert credential.scopes == ["events:write"]


def test_provisioning_rejects_unknown_store_type_and_duplicate_device(db):
    with pytest.raises(EdgeDeviceError, match="store does not exist"):
        register_edge_device(db, device_id="camera-x", store_id=999, device_type="fixed_camera")
    store_id, _ = seed_store(db)
    with pytest.raises(EdgeDeviceError, match="unsupported"):
        register_edge_device(db, device_id="camera-x", store_id=store_id, device_type="unknown")
    register_edge_device(db, device_id="camera-x", store_id=store_id, device_type="fixed_camera")
    with pytest.raises(EdgeDeviceError, match="already registered"):
        register_edge_device(db, device_id="camera-x", store_id=store_id, device_type="fixed_camera")


def test_signed_request_authenticates_device_and_consumes_nonce_once(db):
    store_id, _ = seed_store(db)
    register_edge_device(db, device_id="camera-signed", store_id=store_id, device_type="fixed_camera")
    token, credential = issue_edge_device_credential(db, device_id="camera-signed")
    body = b'{"event":"heartbeat"}'
    timestamp = int(datetime.now(timezone.utc).timestamp())
    nonce = "n" * 32
    canonical = _canonical_signed_request(
        credential_id=credential.credential_id, method="POST",
        request_target="/api/v1/edge/events", timestamp=timestamp,
        nonce=nonce, body=body,
    )
    database_verifier_signature = hmac.new(
        bytes.fromhex(credential.secret_sha256), canonical, hashlib.sha256
    ).hexdigest()
    with pytest.raises(EdgeDeviceAuthenticationError):
        authenticate_edge_device_request(
            db, bearer_token=token, method="POST", request_target="/api/v1/edge/events",
            timestamp=timestamp, nonce=nonce, signature=database_verifier_signature, body=body,
        )
    signature = sign_edge_device_request(
        bearer_token=token, method="POST", request_target="/api/v1/edge/events",
        timestamp=timestamp, nonce=nonce, body=body,
    )
    principal = authenticate_edge_device_request(
        db, bearer_token=token, method="POST", request_target="/api/v1/edge/events",
        timestamp=timestamp, nonce=nonce, signature=signature, body=body,
    )
    assert principal.device_id == "camera-signed"
    assert principal.store_id == store_id
    with pytest.raises(EdgeDeviceReplayError):
        authenticate_edge_device_request(
            db, bearer_token=token, method="POST", request_target="/api/v1/edge/events",
            timestamp=timestamp, nonce=nonce, signature=signature, body=body,
        )


def test_signed_request_rejects_tampered_body_wrong_signature_and_expired_timestamp(db):
    store_id, _ = seed_store(db)
    register_edge_device(db, device_id="camera-tamper", store_id=store_id, device_type="fixed_camera")
    token, _ = issue_edge_device_credential(db, device_id="camera-tamper")
    timestamp = int(datetime.now(timezone.utc).timestamp())
    nonce = "x" * 32
    signature = sign_edge_device_request(
        bearer_token=token, method="POST", request_target="/api/v1/edge/events",
        timestamp=timestamp, nonce=nonce, body=b"original",
    )
    with pytest.raises(EdgeDeviceAuthenticationError):
        authenticate_edge_device_request(
            db, bearer_token=token, method="POST", request_target="/api/v1/edge/events",
            timestamp=timestamp, nonce=nonce, signature=signature, body=b"tampered",
        )
    with pytest.raises(EdgeDeviceAuthenticationError, match="timestamp"):
        authenticate_edge_device_request(
            db, bearer_token=token, method="POST", request_target="/api/v1/edge/events",
            timestamp=timestamp - 1000, nonce="y" * 32, signature=signature, body=b"original",
        )


def test_ingestion_is_idempotent_and_advances_monotonic_cursor(db):
    store_id, shelf_id = seed_store(db)
    register_edge_device(db, device_id="camera-ingest", store_id=store_id, device_type="fixed_camera")
    token, credential = issue_edge_device_credential(db, device_id="camera-ingest")
    principal = type("Principal", (), {
        "device_id": "camera-ingest", "store_id": store_id,
        "credential_id": credential.credential_id, "scopes": frozenset({"events:write"}),
    })()
    event = make_event("camera-ingest", store_id, shelf_id=shelf_id, sequence=1)
    accepted = ingest_edge_event(db, principal=principal, event=event)
    duplicate = ingest_edge_event(db, principal=principal, event=event)
    assert accepted.disposition == "NEXT"
    assert accepted.duplicate is False
    assert duplicate.disposition == "DUPLICATE"
    assert duplicate.duplicate is True
    cursor = db.query(models.EdgeDeviceEventCursor).filter_by(device_id="camera-ingest").one()
    assert cursor.last_sequence == 1
    assert db.query(models.EdgeDeviceEventInbox).filter_by(device_id="camera-ingest").count() == 1


def test_ingestion_rejects_sequence_gap_and_event_id_reuse_with_changed_payload(db):
    store_id, _ = seed_store(db)
    register_edge_device(db, device_id="camera-sequence", store_id=store_id, device_type="gateway")
    _, credential = issue_edge_device_credential(db, device_id="camera-sequence")
    principal = type("Principal", (), {
        "device_id": "camera-sequence", "store_id": store_id,
        "credential_id": credential.credential_id, "scopes": frozenset({"events:write"}),
    })()
    first = make_event("camera-sequence", store_id, sequence=1)
    ingest_edge_event(db, principal=principal, event=first)
    with pytest.raises(EdgeDeviceReplayError, match="gap"):
        ingest_edge_event(db, principal=principal, event=make_event("camera-sequence", store_id, sequence=3))
    changed = EdgeEventEnvelope.model_validate({
        **first.model_dump(mode="json"),
        "payload": {"firmware_version": "9.9.9"},
    })
    with pytest.raises(EdgeEventContractError, match="reused with different content"):
        ingest_edge_event(db, principal=principal, event=changed)


def test_ingestion_rejects_cross_store_device_and_foreign_shelf(db):
    store_a, shelf_a = seed_store(db, "EDGE-A")
    store_b, shelf_b = seed_store(db, "EDGE-B")
    register_edge_device(db, device_id="camera-tenant-a", store_id=store_a, device_type="fixed_camera")
    _, credential = issue_edge_device_credential(db, device_id="camera-tenant-a")
    principal = type("Principal", (), {
        "device_id": "camera-tenant-a", "store_id": store_a,
        "credential_id": credential.credential_id, "scopes": frozenset({"events:write"}),
    })()
    with pytest.raises(EdgeDeviceAuthorizationError, match="identity"):
        ingest_edge_event(db, principal=principal, event=make_event("camera-tenant-a", store_b))
    with pytest.raises(EdgeDeviceAuthorizationError, match="shelf"):
        ingest_edge_event(db, principal=principal, event=make_event("camera-tenant-a", store_a, shelf_id=shelf_b))


def test_credential_rotation_revocation_and_device_disablement_invalidate_principal(db):
    store_id, _ = seed_store(db)
    register_edge_device(db, device_id="camera-lifecycle", store_id=store_id, device_type="mobile")
    old_token, old = issue_edge_device_credential(db, device_id="camera-lifecycle")
    new_token, new = issue_edge_device_credential(db, device_id="camera-lifecycle", rotate=True)
    assert old.revoked_at is not None
    assert old.replaced_by_credential_id == new.credential_id
    assert old_token != new_token
    assert revoke_edge_device_credential(db, credential_id=new.credential_id)
    assert not revoke_edge_device_credential(db, credential_id=new.credential_id)
    assert disable_edge_device(db, device_id="camera-lifecycle")
    assert not disable_edge_device(db, device_id="camera-lifecycle")
    with pytest.raises(EdgeDeviceError, match="disabled"):
        issue_edge_device_credential(db, device_id="camera-lifecycle")
