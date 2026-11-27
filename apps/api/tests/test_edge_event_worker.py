from datetime import datetime, timezone
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.edge_event_worker import (
    BUILTIN_TRANSACTIONAL_HANDLERS,
    EdgeEventHandlerError,
    process_one_edge_event,
)


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


def test_worker_dead_letters_event_without_registered_domain_handler(session_factory, caplog):
    assert process_one_edge_event(
        session_factory, worker_id="edge-worker-a", handlers={}
    )
    row = _processing(session_factory)
    assert row.status == "DEAD_LETTER"
    assert row.last_error_code == "HANDLER_NOT_IMPLEMENTED"
    assert row.finished_at is not None
    assert "edge_event_outcome outcome=DEAD_LETTER" in caplog.text
    assert "error_code=HANDLER_NOT_IMPLEMENTED" in caplog.text


def test_worker_retries_transient_handler_failure(session_factory, caplog):
    private_detail = "private diagnostic must not be persisted"
    def transient_failure(_event):
        raise RuntimeError(private_detail)

    assert process_one_edge_event(
        session_factory,
        worker_id="edge-worker-a",
        handlers={"DEVICE_HEARTBEAT": transient_failure},
    )
    row = _processing(session_factory)
    assert row.status == "RETRY"
    assert row.last_error_code == "WORKER_ERROR"
    assert row.finished_at is None
    assert private_detail not in caplog.text


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


def test_worker_abandons_result_when_lease_renewal_fails(session_factory, monkeypatch, caplog):
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
    assert "database connection interrupted" not in caplog.text


@pytest.mark.parametrize(
    "handler_error",
    [
        RuntimeError("transient handler failure"),
        EdgeEventHandlerError("INVALID_CAPTURE", retryable=False),
    ],
    ids=["retryable-handler-error", "permanent-handler-error"],
)
def test_worker_does_not_change_state_after_lease_renewal_failure(
    session_factory, monkeypatch, handler_error
):
    renewal_failed = threading.Event()

    def fail_renewal(*_args, **_kwargs):
        renewal_failed.set()
        raise RuntimeError("database connection interrupted")

    monkeypatch.setattr("app.edge_event_worker.renew_edge_event_lease", fail_renewal)

    def failing_handler(_event):
        assert renewal_failed.wait(timeout=4)
        raise handler_error

    assert process_one_edge_event(
        session_factory,
        worker_id="edge-worker-a",
        lease_seconds=5,
        handlers={"DEVICE_HEARTBEAT": failing_handler},
    )

    row = _processing(session_factory)
    assert row.status == "PROCESSING"
    assert row.lease_owner == "edge-worker-a"
    assert row.finished_at is None


def test_transactional_handler_commits_domain_work_with_processing(session_factory):
    def handler(db, claim):
        device = db.get(models.EdgeDevice, claim["device_id"])
        device.firmware_version = "atomic-test"
    assert process_one_edge_event(
        session_factory, worker_id="edge-worker-atomic",
        transactional_handlers={"DEVICE_HEARTBEAT": handler},
    )
    assert _processing(session_factory).status == "PROCESSED"
    with session_factory() as db:
        assert db.get(models.EdgeDevice, "edge-worker-camera").firmware_version == "atomic-test"


def test_transactional_handler_failure_rolls_back_domain_work(session_factory):
    def handler(db, claim):
        device = db.get(models.EdgeDevice, claim["device_id"])
        device.firmware_version = "rollback-test"
        raise RuntimeError("transaction failed")
    assert process_one_edge_event(
        session_factory, worker_id="edge-worker-atomic",
        transactional_handlers={"DEVICE_HEARTBEAT": handler},
    )
    assert _processing(session_factory).status == "RETRY"
    with session_factory() as db:
        assert db.get(models.EdgeDevice, "edge-worker-camera").firmware_version is None


def test_worker_routes_task_acknowledgement_through_fenced_transaction(session_factory, caplog):
    from datetime import timedelta
    from types import SimpleNamespace

    from app.edge_task_assignment_service import create_edge_task_assignment

    # Drain the fixture heartbeat so the ACK is the next claim.
    assert process_one_edge_event(session_factory, worker_id="edge-worker-ack")

    now = datetime.now(timezone.utc)
    with session_factory() as db:
        store = db.query(models.Store).filter_by(code="EDGE-WORKER-STORE").one()
        device = db.get(models.EdgeDevice, "edge-worker-camera")
        user = models.User(
            email="edge-worker-ack@example.test",
            store_id=store.id,
            full_name="ACK Supervisor",
            password_hash="not-a-real-password-hash",
            role="SUPERVISOR",
            is_active=True,
        )
        zone = models.Zone(store_id=store.id, name="ACK zone")
        product = models.Product(sku="EDGE-WORKER-ACK-SKU", name="ACK product", unit="un")
        db.add_all([user, zone, product])
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code="EDGE-WORKER-ACK-SHELF")
        db.add(shelf)
        db.flush()
        task = models.ReplenishmentTask(
            store_id=store.id, shelf_id=shelf.id, product_id=product.id,
            status="PENDING", priority="NORMAL",
        )
        db.add(task)
        db.commit()
        task_id = task.id
        task_version = task.task_version
        store_id = store.id
        device_id = device.device_id
        actor = SimpleNamespace(
            id=user.id, role=user.role, store_id=user.store_id, is_active=True,
        )
        create_edge_task_assignment(
            db, store_id=store_id, task_id=task_id, device_id=device_id,
            actor=actor, reason="Teste de encaminhamento transaccional",
            valid_from=now - timedelta(minutes=1),
            valid_until=now + timedelta(hours=1),
        )
        inbox = models.EdgeDeviceEventInbox(
            device_id=device_id,
            event_id="00000000-0000-4000-8000-000000000103",
            sequence_number=3, event_type="TASK_ACKNOWLEDGED",
            store_id=store_id, shelf_id=None, occurred_at=now,
            payload={"task_id": task_id, "task_version": task_version, "action": "COMPLETED"},
            fingerprint_sha256="b" * 64, received_at=now,
        )
        db.add(inbox)
        db.flush()
        inbox_id = inbox.id
        db.add(models.EdgeDeviceEventProcessing(
            inbox_id=inbox_id, status="PENDING", attempt_count=0,
            max_attempts=8, available_at=now, fencing_token=0,
            created_at=now, updated_at=now,
        ))
        db.commit()

    movement_count_before = 0
    with session_factory() as db:
        movement_count_before = db.query(models.InventoryMovement).count()

    assert process_one_edge_event(
        session_factory, worker_id="edge-worker-ack",
        transactional_handlers=BUILTIN_TRANSACTIONAL_HANDLERS,
    )

    with session_factory() as db:
        processing = db.query(models.EdgeDeviceEventProcessing).filter_by(inbox_id=inbox_id).one()
        acknowledgement = db.query(models.EdgeTaskAcknowledgement).filter_by(inbox_id=inbox_id).one()
        task = db.get(models.ReplenishmentTask, task_id)
        assert processing.status == "PROCESSED"
        assert acknowledgement.action == "COMPLETED"
        assert acknowledgement.result == "REVIEW_REQUIRED"
        assert acknowledgement.fingerprint_sha256 == "b" * 64
        assert task.status == "PENDING"
        assert task.task_version == task_version
        assert task.completed_at is None
        assert db.query(models.InventoryMovement).count() == movement_count_before

    assert "edge_event_outcome outcome=ACK_RECORDED" in caplog.text
    assert "event_id=00000000-0000-4000-8000-000000000103" in caplog.text
    assert "duration_ms=" in caplog.text
