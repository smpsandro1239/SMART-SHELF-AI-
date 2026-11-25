from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.edge_event_processing import (
    EdgeEventProcessingError,
    claim_next_edge_event,
    complete_edge_event,
    fail_edge_event,
    renew_edge_event_lease,
)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'edge-processing.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed_event(db, *, max_attempts=8):
    store = models.Store(code="PROCESSING-STORE", name="Processing Store")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zone A")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="SHELF-A")
    db.add(shelf)
    db.flush()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    inbox = models.EdgeDeviceEventInbox(
        device_id="edge-camera-a", event_id="00000000-0000-4000-8000-000000000001",
        sequence_number=1, event_type="DEVICE_HEARTBEAT", store_id=store.id,
        shelf_id=None, occurred_at=now, payload={"network_status": "ONLINE"},
        fingerprint_sha256="a" * 64, received_at=now,
    )
    db.add(inbox)
    db.flush()
    processing = models.EdgeDeviceEventProcessing(
        inbox_id=inbox.id, status="PENDING", attempt_count=0,
        max_attempts=max_attempts, available_at=now, fencing_token=0,
        created_at=now, updated_at=now,
    )
    db.add(processing)
    db.commit()
    return processing.id, now


def test_claim_and_complete_event_with_fenced_lease(db):
    processing_id, now = seed_event(db)
    claim = claim_next_edge_event(db, worker_id="worker-a", lease_seconds=30, now=now)
    assert claim is not None
    assert claim["processing_id"] == processing_id
    assert claim["event_type"] == "DEVICE_HEARTBEAT"
    assert claim["attempt_count"] == 1
    assert claim["fencing_token"] == 1

    complete_edge_event(
        db, processing_id=processing_id, worker_id="worker-a",
        fencing_token=claim["fencing_token"], now=now + timedelta(seconds=1),
    )
    row = db.get(models.EdgeDeviceEventProcessing, processing_id)
    assert row.status == "PROCESSED"
    assert row.lease_owner is None
    assert row.finished_at is not None


def test_expired_lease_is_reclaimed_and_old_worker_is_fenced(db):
    processing_id, now = seed_event(db)
    first = claim_next_edge_event(db, worker_id="worker-a", lease_seconds=5, now=now)
    second = claim_next_edge_event(
        db, worker_id="worker-b", lease_seconds=30, now=now + timedelta(seconds=6)
    )
    assert second["fencing_token"] == first["fencing_token"] + 1
    with pytest.raises(EdgeEventProcessingError, match="stale"):
        complete_edge_event(
            db, processing_id=processing_id, worker_id="worker-a",
            fencing_token=first["fencing_token"], now=now + timedelta(seconds=7),
        )
    complete_edge_event(
        db, processing_id=processing_id, worker_id="worker-b",
        fencing_token=second["fencing_token"], now=now + timedelta(seconds=7),
    )


def test_retry_uses_exponential_delay_and_dead_letters_at_attempt_limit(db):
    processing_id, now = seed_event(db, max_attempts=2)
    first = claim_next_edge_event(db, worker_id="worker-a", now=now)
    state = fail_edge_event(
        db, processing_id=processing_id, worker_id="worker-a",
        fencing_token=first["fencing_token"], error_code="TEMPORARY_FAILURE", now=now,
    )
    assert state == "RETRY"
    row = db.get(models.EdgeDeviceEventProcessing, processing_id)
    assert row.available_at.replace(tzinfo=timezone.utc) == now + timedelta(seconds=2)

    assert claim_next_edge_event(
        db, worker_id="worker-b", now=now + timedelta(seconds=3)
    ) is not None
    second = db.get(models.EdgeDeviceEventProcessing, processing_id)
    state = fail_edge_event(
        db, processing_id=processing_id, worker_id="worker-b",
        fencing_token=second.fencing_token, error_code="INVALID_EVENT",
        retryable=True, now=now + timedelta(seconds=3),
    )
    assert state == "DEAD_LETTER"
    row = db.get(models.EdgeDeviceEventProcessing, processing_id)
    assert row.finished_at is not None
    assert row.last_error_code == "INVALID_EVENT"


def test_worker_identity_and_lease_bounds_are_validated(db):
    processing_id, now = seed_event(db)
    with pytest.raises(ValueError, match="worker_id"):
        claim_next_edge_event(db, worker_id="../unsafe", now=now)
    with pytest.raises(ValueError, match="lease_seconds"):
        claim_next_edge_event(db, worker_id="worker-a", lease_seconds=1, now=now)
    assert db.get(models.EdgeDeviceEventProcessing, processing_id).status == "PENDING"


def test_lease_renewal_extends_current_lease_without_shortening_it(db):
    processing_id, now = seed_event(db)
    claim = claim_next_edge_event(db, worker_id="worker-a", lease_seconds=30, now=now)
    original_expiry = claim["lease_expires_at"]
    renewed = renew_edge_event_lease(
        db, processing_id=processing_id, worker_id="worker-a",
        fencing_token=claim["fencing_token"], lease_seconds=60,
        now=now + timedelta(seconds=5),
    )
    assert renewed == now + timedelta(seconds=65)
    assert renewed > original_expiry

    unchanged = renew_edge_event_lease(
        db, processing_id=processing_id, worker_id="worker-a",
        fencing_token=claim["fencing_token"], lease_seconds=5,
        now=now + timedelta(seconds=6),
    )
    assert unchanged == renewed


def test_expired_or_fenced_worker_cannot_renew_lease(db):
    processing_id, now = seed_event(db)
    first = claim_next_edge_event(db, worker_id="worker-a", lease_seconds=5, now=now)
    second = claim_next_edge_event(
        db, worker_id="worker-b", lease_seconds=30, now=now + timedelta(seconds=6)
    )
    with pytest.raises(EdgeEventProcessingError, match="stale"):
        renew_edge_event_lease(
            db, processing_id=processing_id, worker_id="worker-a",
            fencing_token=first["fencing_token"], lease_seconds=60,
            now=now + timedelta(seconds=7),
        )
    with pytest.raises(EdgeEventProcessingError, match="stale"):
        renew_edge_event_lease(
            db, processing_id=processing_id, worker_id="worker-b",
            fencing_token=second["fencing_token"], lease_seconds=60,
            now=now + timedelta(seconds=37),
        )


def test_lease_renewal_validates_arguments(db):
    processing_id, now = seed_event(db)
    claim = claim_next_edge_event(db, worker_id="worker-a", now=now)
    with pytest.raises(ValueError, match="lease_seconds"):
        renew_edge_event_lease(
            db, processing_id=processing_id, worker_id="worker-a",
            fencing_token=claim["fencing_token"], lease_seconds=1, now=now,
        )
    with pytest.raises(ValueError, match="fencing_token"):
        renew_edge_event_lease(
            db, processing_id=processing_id, worker_id="worker-a",
            fencing_token=0, lease_seconds=30, now=now,
        )
