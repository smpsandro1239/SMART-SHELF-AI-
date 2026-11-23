from datetime import datetime, timezone
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.edge_event_worker import EdgeEventHandlerError, process_one_edge_event


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'edge-worker.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        store = models.Store(code="EDGE-WORKER-STORE", name="Edge Worker Store")
        db.add(store)
        db.flush()
        device = models.EdgeDevice(
            device_id="edge-worker-camera", store_id=store.id,
            device_type="fixed_camera", status="ACTIVE",
        )
        db.add(device)
        db.flush()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        inbox = models.EdgeDeviceEventInbox(
            device_id=device.device_id,
            event_id="00000000-0000-4000-8000-000000000001",
            sequence_number=1, event_type="DEVICE_HEARTBEAT",
            store_id=store.id, shelf_id=None, occurred_at=now,
            payload={"network_status": "ONLINE"},
            fingerprint_sha256="a" * 64, received_at=now,
        )
        db.add(inbox)
        db.flush()
        db.add(models.EdgeDeviceEventProcessing(
            inbox_id=inbox.id, status="PENDING", attempt_count=0,
            max_attempts=8, available_at=now, fencing_token=0,
            created_at=now, updated_at=now,
        ))
        db.commit()
    yield factory
    engine.dispose()


def _processing(factory):
    with factory() as db:
        return db.query(models.EdgeDeviceEventProcessing).one()


def test_worker_processes_heartbeat_and_completes_inbox(session_factory):
    assert process_one_edge_event(session_factory, worker_id="edge-worker-a")
    row = _processing(session_factory)
    assert row.status == "PROCESSED"
    assert row.attempt_count == 1
    assert row.fencing_token == 1
    assert row.lease_owner is None
    assert not process_one_edge_event(session_factory, worker_id="edge-worker-a")


def test_worker_dead_letters_event_without_registered_domain_handler(session_factory):
    assert process_one_edge_event(
        session_factory, worker_id="edge-worker-a", handlers={}
    )
    row = _processing(session_factory)
    assert row.status == "DEAD_LETTER"
    assert row.last_error_code == "HANDLER_NOT_IMPLEMENTED"
    assert row.finished_at is not None


def test_worker_retries_transient_handler_failure(session_factory):
    def transient_failure(_event):
        raise RuntimeError("private diagnostic must not be persisted")

    assert process_one_edge_event(
        session_factory,
        worker_id="edge-worker-a",
        handlers={"DEVICE_HEARTBEAT": transient_failure},
    )
    row = _processing(session_factory)
    assert row.status == "RETRY"
    assert row.last_error_code == "WORKER_ERROR"
    assert row.finished_at is None


def test_worker_respects_explicit_non_retryable_handler_failure(session_factory):
    def permanent_failure(_event):
        raise EdgeEventHandlerError("INVALID_CAPTURE", retryable=False)

    assert process_one_edge_event(
        session_factory,
        worker_id="edge-worker-a",
        handlers={"DEVICE_HEARTBEAT": permanent_failure},
    )
    row = _processing(session_factory)
    assert row.status == "DEAD_LETTER"
    assert row.last_error_code == "INVALID_CAPTURE"


def test_worker_abandons_result_when_lease_renewal_fails(session_factory, monkeypatch):
    renewal_started = threading.Event()

    def fail_renewal(*_args, **_kwargs):
        renewal_started.set()
        raise RuntimeError("database connection interrupted")

    monkeypatch.setattr("app.edge_event_worker.renew_edge_event_lease", fail_renewal)

    def wait_for_renewal_failure(_event):
        assert renewal_started.wait(timeout=4)

    assert process_one_edge_event(
        session_factory,
        worker_id="edge-worker-a",
        lease_seconds=5,
        handlers={"DEVICE_HEARTBEAT": wait_for_renewal_failure},
    )
    row = _processing(session_factory)
    # A failed heartbeat must never be followed by a local acknowledgement.
    # The lease remains recoverable after expiry by a worker with a new fence.
    assert row.status == "PROCESSING"
    assert row.lease_owner == "edge-worker-a"
    assert row.finished_at is None
