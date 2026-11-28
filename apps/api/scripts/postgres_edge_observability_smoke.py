"""PostgreSQL 16 smoke for Edge observability crash recovery and isolation.

Uses only the disposable PostgreSQL service provisioned by API CI. It verifies
transaction rollback after backend termination, concurrent replay/idempotency,
real supervisor-event persistence, bounded retention, and business-ledger
immutability. It does not modify ACK, tasks, inventory, or source inbox data.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from multiprocessing import get_context
from threading import Barrier
from uuid import uuid4

from sqlalchemy import select, text

from app import models
from app.database import SessionLocal, engine
from app.edge_observability_worker import aggregate_cycle, floor_window, purge_expired
from app.edge_supervisor_events import AsyncSupervisorEventWriter


def _seed_fixture():
    now = floor_window(datetime.now(timezone.utc), timedelta(minutes=15)) + timedelta(minutes=5)
    window_15m = floor_window(now, timedelta(minutes=15)) - timedelta(minutes=15)
    window_daily = floor_window(now, timedelta(days=1)) - timedelta(days=1)
    old = now - timedelta(days=91)
    suffix = uuid4().hex[:12]

    with SessionLocal() as db:
        store = models.Store(code=f"EDGE-OBS-{suffix}", name="Edge observability smoke")
        db.add(store)
        db.flush()
        device_id = f"edge-observability-{suffix}"
        db.add(models.EdgeDevice(
            device_id=device_id,
            store_id=store.id,
            device_type="gateway",
            status="ACTIVE",
        ))
        db.flush()

        received = [
            window_15m + timedelta(minutes=2),
            window_15m + timedelta(minutes=4),
            window_daily + timedelta(hours=10),
            window_daily + timedelta(hours=11),
            window_daily + timedelta(hours=12),
        ]
        inbox_rows = []
        for sequence, occurred_at in enumerate(received, start=1):
            row = models.EdgeDeviceEventInbox(
                device_id=device_id,
                event_id=str(uuid4()),
                sequence_number=sequence,
                event_type="DEVICE_HEARTBEAT",
                store_id=store.id,
                shelf_id=None,
                occurred_at=occurred_at,
                payload={"smoke": "edge-observability"},
                fingerprint_sha256=uuid4().hex + uuid4().hex,
                received_at=occurred_at,
            )
            inbox_rows.append(row)
        db.add_all(inbox_rows)
        db.flush()

        # Seed checkpoints so the smoke replays only a small, known window set.
        db.add_all([
            models.EdgeObservabilityCheckpoint(
                job_name="edge-observability-15m-v1",
                last_completed_window=window_15m + timedelta(minutes=15),
                updated_at=now,
            ),
            models.EdgeObservabilityCheckpoint(
                job_name="edge-observability-daily-v1",
                last_completed_window=window_daily + timedelta(days=1),
                updated_at=now,
            ),
        ])
        db.commit()
        return store.id, device_id, now, window_15m, window_daily, old, inbox_rows[-1].id


def _interrupt_transaction(queue, release_event, now, target_window):
    import app.edge_observability_worker as worker

    original = worker._aggregate_window

    def aggregate_then_pause(db, granularity, window_start, window_end, updated_at):
        result = original(db, granularity, window_start, window_end, updated_at)
        if granularity == "15m" and window_start == target_window:
            backend_pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            queue.put(backend_pid)
            release_event.wait(timeout=30)
        return result

    worker._aggregate_window = aggregate_then_pause
    worker.aggregate_cycle(SessionLocal, now=now, max_windows_per_granularity=96)


def _run_concurrent_aggregate(now):
    barrier = Barrier(2)

    def run():
        barrier.wait(timeout=15)
        return aggregate_cycle(
            SessionLocal,
            now=now,
            max_windows_per_granularity=96,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(lambda _index: run(), range(2)))


def _count(db, table_name):
    return int(db.execute(text(f"SELECT count(*) FROM {table_name}")).scalar_one())


def main():
    with SessionLocal() as db:
        version = int(db.execute(text("SHOW server_version_num")).scalar_one())
        assert 160000 <= version < 170000, f"expected PostgreSQL 16, got {version}"

    store_id, device_id, now, window_15m, window_daily, old, old_inbox_id = _seed_fixture()

    # Kill the PostgreSQL backend after aggregate rows have been written inside
    # the transaction but before the checkpoint/aggregate transaction commits.
    context = get_context("spawn")
    backend_queue = context.Queue()
    release_event = context.Event()
    process = context.Process(
        target=_interrupt_transaction,
        args=(backend_queue, release_event, now, window_15m),
        name="edge-observability-interrupted-transaction",
    )
    process.start()
    try:
        backend_pid = backend_queue.get(timeout=45)
        with SessionLocal() as administrator:
            terminated = administrator.execute(
                text("SELECT pg_terminate_backend(:pid)"),
                {"pid": backend_pid},
            ).scalar_one()
        assert terminated is True, "failed to terminate observability transaction backend"
        release_event.set()
        process.join(timeout=20)
        assert not process.is_alive(), "interrupted aggregation process did not exit"
        assert process.exitcode != 0, "terminated transaction unexpectedly committed"
    finally:
        release_event.set()
        if process.is_alive():
            process.kill()
            process.join(timeout=15)

    # The interrupted transaction must leave neither a partial aggregate nor
    # an advanced checkpoint. The independent worker can then replay safely.
    with SessionLocal() as db:
        checkpoint = db.get(models.EdgeObservabilityCheckpoint, "edge-observability-15m-v1")
        assert checkpoint is not None
        assert checkpoint.last_completed_window == window_15m + timedelta(minutes=15)
        partial = db.scalar(select(models.EdgeObservabilityAggregate.id).where(
            models.EdgeObservabilityAggregate.store_id == store_id,
            models.EdgeObservabilityAggregate.granularity == "15m",
            models.EdgeObservabilityAggregate.window_start == window_15m,
        ))
        assert partial is None, "interrupted transaction left a partial aggregate"

    aggregate_cycle(SessionLocal, now=now, max_windows_per_granularity=96)
    _run_concurrent_aggregate(now)

    with SessionLocal() as db:
        fifteen = db.scalars(select(models.EdgeObservabilityAggregate).where(
            models.EdgeObservabilityAggregate.store_id == store_id,
            models.EdgeObservabilityAggregate.granularity == "15m",
            models.EdgeObservabilityAggregate.window_start == window_15m,
            models.EdgeObservabilityAggregate.metric_name == "events_received",
            models.EdgeObservabilityAggregate.dimension_value == "ALL",
        )).all()
        daily = db.scalars(select(models.EdgeObservabilityAggregate).where(
            models.EdgeObservabilityAggregate.store_id == store_id,
            models.EdgeObservabilityAggregate.granularity == "daily",
            models.EdgeObservabilityAggregate.window_start == window_daily,
            models.EdgeObservabilityAggregate.metric_name == "events_received",
            models.EdgeObservabilityAggregate.dimension_value == "ALL",
        )).all()
        assert len(fifteen) == 1 and fifteen[0].value_count == 2, fifteen
        assert len(daily) == 1 and daily[0].value_count == 3, daily

    # Exercise the actual asynchronous writer against PostgreSQL, not only a
    # fake session. The bounded queue must flush before graceful shutdown.
    supervisor_instance = f"pg-smoke-{uuid4().hex}"
    writer = AsyncSupervisorEventWriter(SessionLocal, max_queue_size=8)
    writer.start()
    assert writer.emit(
        event_type="RESTARTING",
        supervisor_instance_id=supervisor_instance,
        worker_id="edge-observability-smoke",
        reason_code="CHILD_EXITED",
        restart_count=1,
        exit_code=1,
    )
    writer.close(timeout=10)
    if writer._thread is None or writer._thread.is_alive():
        raise AssertionError("supervisor event writer did not drain before shutdown")

    with SessionLocal() as db:
        persisted = db.scalar(select(models.EdgeSupervisorEvent.id).where(
            models.EdgeSupervisorEvent.supervisor_instance_id == supervisor_instance,
            models.EdgeSupervisorEvent.event_type == "RESTARTING",
        ))
        assert persisted is not None, "supervisor event was not persisted to PostgreSQL"

        # Add expired observability artefacts plus old business-source rows.
        old_aggregate = models.EdgeObservabilityAggregate(
            store_id=store_id,
            granularity="daily",
            window_start=old,
            metric_name="events_received",
            dimension_value="ALL",
            value_count=99,
            updated_at=old,
        )
        old_supervisor = models.EdgeSupervisorEvent(
            event_key=uuid4().hex + uuid4().hex,
            supervisor_instance_id=f"expired-{uuid4().hex}",
            event_type="STOPPED",
            worker_id="expired-worker",
            reason_code="SHUTDOWN_REQUESTED",
            restart_count=0,
            occurred_at=old,
        )
        old_inbox = models.EdgeDeviceEventInbox(
            device_id=device_id,
            event_id=str(uuid4()),
            sequence_number=6,
            event_type="DEVICE_HEARTBEAT",
            store_id=store_id,
            shelf_id=None,
            occurred_at=old,
            payload={"smoke": "retention-source-must-remain"},
            fingerprint_sha256=uuid4().hex + uuid4().hex,
            received_at=old,
        )
        db.add_all([old_aggregate, old_supervisor, old_inbox])
        db.flush()
        old_processing = models.EdgeDeviceEventProcessing(
            inbox_id=old_inbox.id,
            status="PENDING",
            attempt_count=0,
            max_attempts=8,
            available_at=old,
            fencing_token=0,
            created_at=old,
            updated_at=old,
        )
        db.add(old_processing)
        db.commit()
        old_processing_id = old_processing.id

    with SessionLocal() as before:
        business_counts = {
            table: _count(before, table)
            for table in (
                "edge_device_event_inbox",
                "edge_device_event_processing",
                "edge_task_acknowledgements",
                "edge_task_acknowledgement_reviews",
                "edge_device_audit_events",
                "inventory_movements",
            )
        }

    deleted = purge_expired(SessionLocal, now=now, retention_days=90, batch_size=1)
    assert deleted == {"aggregates": 1, "supervisor_events": 1}, deleted

    with SessionLocal() as db:
        assert db.get(models.EdgeDeviceEventInbox, old_inbox_id) is not None
        assert db.get(models.EdgeDeviceEventProcessing, old_processing_id) is not None
        assert db.scalar(select(models.EdgeObservabilityAggregate.id).where(
            models.EdgeObservabilityAggregate.store_id == store_id,
            models.EdgeObservabilityAggregate.window_start == old,
        )) is None
        assert db.scalar(select(models.EdgeSupervisorEvent.id).where(
            models.EdgeSupervisorEvent.occurred_at == old,
        )) is None
        business_counts_after = {
            table: _count(db, table)
            for table in business_counts
        }
        assert business_counts_after == business_counts, {
            "before": business_counts,
            "after": business_counts_after,
        }

    print(
        "PostgreSQL 16 Edge observability smoke passed: interrupted transaction "
        "rolled back, replay and concurrent aggregation remained idempotent, "
        "15-minute/daily windows were store-scoped, supervisor events persisted, "
        "retention was bounded, and business ledgers remained unchanged."
    )


if __name__ == "__main__":
    main()
