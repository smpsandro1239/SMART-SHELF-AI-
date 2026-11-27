"""Exercise Edge worker session loss and a real PostgreSQL 16 outage.

This destructive fault-injection smoke is restricted to the disposable
PostgreSQL service container created by GitHub Actions API CI. It separately
tests pg_terminate_backend (one session), stopping the PostgreSQL service,
restoring the service, lease loss, takeover and stale-fence rejection.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import multiprocessing
import os
import subprocess
import time
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app import models
from app.database import SessionLocal, engine
from app.edge_event_processing import (
    EdgeEventProcessingError,
    claim_next_edge_event,
    complete_edge_event,
)
from app.edge_event_worker import process_one_edge_event


LEASE_SECONDS = 5
WORKER_ID = "edge-outage-worker-old"


def _blocking_worker(ready_queue, release_event, inbox_id: int) -> None:
    """Run the real worker loop against one deterministic no-op heartbeat."""
    def handler(event: dict) -> None:
        if event["inbox_id"] != inbox_id:
            raise AssertionError("worker claimed an event outside the fault fixture")
        ready_queue.put({
            "phase": "handler_started",
            "processing_id": event["processing_id"],
            "inbox_id": event["inbox_id"],
            "fencing_token": event["fencing_token"],
        })
        if not release_event.wait(45):
            raise AssertionError("fault-injection handler timed out")

    try:
        processed = process_one_edge_event(
            SessionLocal,
            worker_id=WORKER_ID,
            lease_seconds=LEASE_SECONDS,
            handlers={"DEVICE_HEARTBEAT": handler},
        )
        ready_queue.put({"phase": "worker_finished", "processed": processed})
    except Exception as exc:
        # Do not send exception text through the multiprocessing channel.
        ready_queue.put({"phase": "worker_error", "error_type": type(exc).__name__})
        raise


def _verify_session_termination_is_scoped() -> None:
    """Kill one backend and prove PostgreSQL itself remains available."""
    victim = SessionLocal()
    try:
        victim_pid = victim.execute(text("SELECT pg_backend_pid()")).scalar_one()
        with SessionLocal() as administrator:
            terminated = administrator.execute(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": victim_pid}
            ).scalar_one()
        assert terminated is True, "PostgreSQL did not terminate the selected backend"

        try:
            victim.execute(text("SELECT 1"))
        except DBAPIError:
            pass
        else:
            raise AssertionError("terminated PostgreSQL session remained usable")
    finally:
        victim.close()

    with SessionLocal() as fresh:
        assert fresh.execute(text("SELECT 1")).scalar_one() == 1
        version = int(fresh.execute(text("SHOW server_version_num")).scalar_one())
        assert 160000 <= version < 170000, f"expected PostgreSQL 16, got {version}"


def _create_fixture() -> tuple[int, int, int, int]:
    suffix = uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        eligible = db.query(models.EdgeDeviceEventProcessing).filter(
            (
                models.EdgeDeviceEventProcessing.status.in_(("PENDING", "RETRY"))
                & (models.EdgeDeviceEventProcessing.available_at <= now)
            )
            | (
                (models.EdgeDeviceEventProcessing.status == "PROCESSING")
                & (models.EdgeDeviceEventProcessing.lease_expires_at <= now)
            )
        ).count()
        if eligible:
            raise AssertionError(
                f"fault fixture requires an idle Edge inbox; found {eligible} eligible rows"
            )

        store_a = models.Store(code=f"EDGE-OUTAGE-A-{suffix}", name="Edge outage store A")
        store_b = models.Store(code=f"EDGE-OUTAGE-B-{suffix}", name="Edge outage store B")
        db.add_all([store_a, store_b])
        db.flush()
        device_a_id = f"edge-outage-a-{suffix}"
        device_b_id = f"edge-outage-b-{suffix}"
        db.add_all([
            models.EdgeDevice(
                device_id=device_a_id, store_id=store_a.id,
                device_type="robot", status="ACTIVE",
            ),
            models.EdgeDevice(
                device_id=device_b_id, store_id=store_b.id,
                device_type="robot", status="ACTIVE",
            ),
        ])
        db.flush()

        inbox_a = models.EdgeDeviceEventInbox(
            device_id=device_a_id, event_id=str(uuid4()), sequence_number=1,
            event_type="DEVICE_HEARTBEAT", store_id=store_a.id, shelf_id=None,
            occurred_at=now, payload={"smoke": "postgres-service-outage"},
            fingerprint_sha256=uuid4().hex + uuid4().hex, received_at=now,
        )
        inbox_b = models.EdgeDeviceEventInbox(
            device_id=device_b_id, event_id=str(uuid4()), sequence_number=1,
            event_type="DEVICE_HEARTBEAT", store_id=store_b.id, shelf_id=None,
            occurred_at=now, payload={"smoke": "tenant-isolation-control"},
            fingerprint_sha256=uuid4().hex + uuid4().hex, received_at=now,
        )
        db.add_all([inbox_a, inbox_b])
        db.flush()
        processing_a = models.EdgeDeviceEventProcessing(
            inbox_id=inbox_a.id, status="PENDING", attempt_count=0, max_attempts=8,
            available_at=now - timedelta(minutes=1), fencing_token=0,
            created_at=now, updated_at=now,
        )
        processing_b = models.EdgeDeviceEventProcessing(
            inbox_id=inbox_b.id, status="PENDING", attempt_count=0, max_attempts=8,
            available_at=now + timedelta(days=1), fencing_token=0,
            created_at=now, updated_at=now,
        )
        db.add_all([processing_a, processing_b])
        db.commit()
        movement_count = db.query(models.InventoryMovement).count()
        return (
            processing_a.id, inbox_a.id, processing_b.id, movement_count
        )


def _postgres_service_container() -> str:
    if os.getenv("GITHUB_ACTIONS") != "true":
        raise RuntimeError(
            "refusing to stop PostgreSQL outside the disposable GitHub Actions service"
        )
    result = subprocess.run(
        ["docker", "ps", "--filter", "ancestor=postgres:16", "--format", "{{.ID}}"],
        check=True, capture_output=True, text=True, timeout=15,
    )
    containers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(containers) != 1:
        raise AssertionError(
            f"expected exactly one postgres:16 service container, found {len(containers)}"
        )
    image = subprocess.run(
        ["docker", "inspect", "--format", "{{.Config.Image}}", containers[0]],
        check=True, capture_output=True, text=True, timeout=15,
    ).stdout.strip()
    if image != "postgres:16":
        raise AssertionError(f"refusing to stop unexpected database image: {image}")
    return containers[0]


def _wait_for_postgres(timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error_type = "not attempted"
    while time.monotonic() < deadline:
        engine.dispose()
        try:
            with SessionLocal() as db:
                version = int(db.execute(text("SHOW server_version_num")).scalar_one())
                if not 160000 <= version < 170000:
                    raise AssertionError(f"expected PostgreSQL 16, got {version}")
                return
        except SQLAlchemyError as exc:
            last_error_type = type(exc).__name__
            time.sleep(0.5)
    raise AssertionError(
        f"PostgreSQL service did not recover within {timeout_seconds}s "
        f"(last_error_type={last_error_type})"
    )


def _verify_real_service_outage_and_takeover() -> None:
    processing_id, inbox_id, control_processing_id, movements_before = _create_fixture()
    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    release_event = context.Event()
    worker = context.Process(
        target=_blocking_worker,
        args=(ready_queue, release_event, inbox_id),
        name="edge-postgres-outage-worker",
    )
    container_id = _postgres_service_container()
    stopped = False
    try:
        worker.start()
        started = ready_queue.get(timeout=30)
        assert started.get("phase") == "handler_started", started
        assert started["inbox_id"] == inbox_id
        assert started["processing_id"] == processing_id

        with SessionLocal() as db:
            claimed = db.get(models.EdgeDeviceEventProcessing, processing_id)
            assert claimed is not None and claimed.status == "PROCESSING"
            assert claimed.lease_owner == WORKER_ID
            old_fence = claimed.fencing_token
            original_expiry = claimed.lease_expires_at
            assert original_expiry is not None

        # Stop the actual PostgreSQL 16 service container, not just one backend.
        subprocess.run(
            ["docker", "stop", "--time", "1", container_id],
            check=True, capture_output=True, text=True, timeout=20,
        )
        stopped = True
        # The worker heartbeat interval is lease_seconds / 3 (>= 1s).
        # Keep PostgreSQL unavailable long enough for a real renewal attempt.
        time.sleep(2.5)
    finally:
        if stopped:
            subprocess.run(
                ["docker", "start", container_id],
                check=True, capture_output=True, text=True, timeout=30,
            )
            _wait_for_postgres()
        release_event.set()

    finished = ready_queue.get(timeout=30)
    assert finished.get("phase") == "worker_finished", finished
    worker.join(timeout=15)
    assert not worker.is_alive(), "old Edge worker did not exit"
    assert worker.exitcode == 0, f"old Edge worker exited with {worker.exitcode}"

    # The failed heartbeat must have caused the worker to abandon its local
    # handler result: the lease timestamp and PROCESSING state remain untouched.
    with SessionLocal() as db:
        abandoned = db.get(models.EdgeDeviceEventProcessing, processing_id)
        assert abandoned is not None
        assert abandoned.status == "PROCESSING"
        assert abandoned.lease_owner == WORKER_ID
        assert abandoned.fencing_token == old_fence
        assert abandoned.lease_expires_at == original_expiry

    remaining = (original_expiry - datetime.now(timezone.utc)).total_seconds()
    if remaining > 0:
        time.sleep(remaining + 0.2)

    recovery_worker_id = "edge-outage-recovery-worker"
    with SessionLocal() as db:
        replacement = claim_next_edge_event(
            db, worker_id=recovery_worker_id, lease_seconds=30
        )
    assert replacement is not None
    assert replacement["processing_id"] == processing_id
    assert replacement["inbox_id"] == inbox_id
    assert replacement["fencing_token"] == old_fence + 1

    try:
        with SessionLocal() as stale_db:
            complete_edge_event(
                stale_db, processing_id=processing_id,
                worker_id=WORKER_ID, fencing_token=old_fence,
            )
    except EdgeEventProcessingError:
        pass
    else:
        raise AssertionError("old worker fencing credentials completed after takeover")

    with SessionLocal() as current_db:
        complete_edge_event(
            current_db, processing_id=processing_id,
            worker_id=recovery_worker_id,
            fencing_token=replacement["fencing_token"],
        )

    with SessionLocal() as verify:
        final = verify.get(models.EdgeDeviceEventProcessing, processing_id)
        control = verify.get(models.EdgeDeviceEventProcessing, control_processing_id)
        assert final is not None and final.status == "PROCESSED"
        assert final.fencing_token == old_fence + 1
        assert final.lease_owner is None and final.lease_expires_at is None
        assert control is not None and control.status == "PENDING"
        assert control.fencing_token == 0 and control.lease_owner is None
        assert verify.query(models.InventoryMovement).count() == movements_before


def main() -> None:
    _verify_session_termination_is_scoped()
    _verify_real_service_outage_and_takeover()
    print(
        "PostgreSQL 16 Edge fault-injection smoke passed: pg_terminate_backend "
        "was session-scoped; the PostgreSQL service was stopped and restored; "
        "the failed heartbeat caused local-result abandonment; lease expiry, "
        "takeover, stale-fence rejection, tenant isolation and inventory "
        "immutability were verified."
    )


if __name__ == "__main__":
    main()
