import json
import os
from datetime import datetime, timezone
from uuid import uuid4

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./edge_http_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.edge_device_service import (
    issue_edge_device_credential,
    register_edge_device,
    sign_edge_device_request,
)
from app.edge_event_contract import EdgeEventEnvelope
from app.edge_ingest_metrics import edge_ingest_metrics_snapshot, reset_edge_ingest_metrics
from app.main import app

ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


def override_get_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_database():
    reset_edge_ingest_metrics()
    previous = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous
    Base.metadata.drop_all(bind=ENGINE)


def seed_device():
    db = Session()
    store = models.Store(code="EDGE-HTTP-STORE", name="Edge HTTP store")
    db.add(store)
    db.flush()
    register_edge_device(
        db, device_id="edge-http-camera", store_id=store.id, device_type="fixed_camera"
    )
    store_id = store.id
    token, credential = issue_edge_device_credential(db, device_id="edge-http-camera")
    credential_id = credential.credential_id
    db.close()
    return store_id, token, credential_id


def build_event(store_id, *, sequence=1, event_id=None):
    return EdgeEventEnvelope(
        schema_version=1,
        event_id=event_id or str(uuid4()),
        event_type="DEVICE_HEARTBEAT",
        device_id="edge-http-camera",
        store_id=store_id,
        sequence_number=sequence,
        occurred_at=datetime.now(timezone.utc),
        payload={"firmware_version": "1.0.0", "network_status": "ONLINE"},
    )


def signed_headers(token, body, *, nonce):
    timestamp = int(datetime.now(timezone.utc).timestamp())
    signature = sign_edge_device_request(
        bearer_token=token,
        method="POST",
        request_target="/api/v1/edge/events",
        timestamp=timestamp,
        nonce=nonce,
        body=body,
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Edge-Timestamp": str(timestamp),
        "X-Edge-Nonce": nonce,
        "X-Edge-Signature": signature,
        "Content-Type": "application/json",
    }


def test_signed_edge_event_http_endpoint_accepts_and_persists_event():
    store_id, token, _ = seed_device()
    event = build_event(store_id)
    body = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/edge/events",
            content=body,
            headers=signed_headers(token, body, nonce="a" * 32),
        )
    assert response.status_code == 202, response.text
    assert response.json()["accepted"] is True
    assert response.json()["disposition"] == "NEXT"
    assert response.json()["duplicate"] is False
    metrics = edge_ingest_metrics_snapshot()
    assert metrics["events_received"] == 1
    assert metrics["events_accepted"] == 1
    assert metrics["events_duplicate"] == 0
    db = Session()
    assert db.query(models.EdgeDeviceEventInbox).count() == 1
    device = db.query(models.EdgeDevice).filter_by(device_id="edge-http-camera").one()
    assert device.last_seen_at is not None
    assert device.last_network_status == "ONLINE"
    assert device.firmware_version == "1.0.0"
    db.close()


def test_edge_http_rejects_missing_or_invalid_signature():
    with TestClient(app) as client:
        missing = client.post("/api/v1/edge/events", content=b"{}")
        invalid = client.post(
            "/api/v1/edge/events",
            content=b"{}",
            headers={
                "Authorization": "Bearer sse1." + "a" * 32 + "." + "b" * 43,
                "X-Edge-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                "X-Edge-Nonce": "b" * 32,
                "X-Edge-Signature": "0" * 64,
            },
        )
    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_edge_http_rejects_reused_nonce_and_cross_tenant_envelope():
    store_id, token, _ = seed_device()
    event = build_event(store_id)
    body = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    headers = signed_headers(token, body, nonce="c" * 32)
    with TestClient(app) as client:
        first = client.post("/api/v1/edge/events", content=body, headers=headers)
        replay = client.post("/api/v1/edge/events", content=body, headers=headers)
    assert first.status_code == 202
    assert replay.status_code == 409

    foreign = build_event(store_id + 1, sequence=2)
    foreign_body = json.dumps(foreign.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/edge/events",
            content=foreign_body,
            headers=signed_headers(token, foreign_body, nonce="d" * 32),
        )
    assert response.status_code == 403


def test_edge_ingest_metrics_distinguish_duplicate_sequence_and_auth_rejection():
    store_id, token, _ = seed_device()
    event = build_event(store_id)
    body = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    with TestClient(app) as client:
        accepted = client.post("/api/v1/edge/events", content=body,
            headers=signed_headers(token, body, nonce="e" * 32))
        duplicate = client.post("/api/v1/edge/events", content=body,
            headers=signed_headers(token, body, nonce="f" * 32))
        stale = build_event(store_id, sequence=1)
        stale_body = json.dumps(stale.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        sequence_conflict = client.post("/api/v1/edge/events", content=stale_body,
            headers=signed_headers(token, stale_body, nonce="g" * 32))
        unauthorized = client.post("/api/v1/edge/events", content=b"{}")
    assert accepted.status_code == 202
    assert duplicate.status_code == 202
    assert sequence_conflict.status_code == 409
    assert unauthorized.status_code == 401
    metrics = edge_ingest_metrics_snapshot()
    assert metrics["events_received"] == 4
    assert metrics["events_accepted"] == 1
    assert metrics["events_duplicate"] == 1
    assert metrics["events_rejected"] == 2
    assert metrics["sequence_conflicts"] == 1
    assert metrics["authentication_rejected"] == 1
