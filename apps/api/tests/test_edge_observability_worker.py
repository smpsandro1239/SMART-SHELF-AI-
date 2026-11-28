"""Service tests for bounded, idempotent Edge observability aggregation."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import models
from app.edge_observability_worker import aggregate_cycle, floor_window, purge_expired


@pytest.fixture
def db_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'observability.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add_all([
            models.Store(id=1, code="STORE-1", name="Store 1"),
            models.Store(id=2, code="STORE-2", name="Store 2"),
        ])
    yield factory
    engine.dispose()


def _add_inbox(factory, store_id, event_type, received_at, sequence):
    with factory.begin() as db:
        device_id = f"device-{store_id}"
        device = db.get(models.EdgeDevice, device_id)
        if device is None:
            device = models.EdgeDevice(
                device_id=device_id, store_id=store_id,
                device_type="gateway", status="ACTIVE",
            )
            db.add(device)
            db.flush()
        db.add(models.EdgeDeviceEventInbox(
            device_id=device.device_id, event_id=str(uuid4()),
            sequence_number=sequence, event_type=event_type, store_id=store_id,
            occurred_at=received_at, payload={}, fingerprint_sha256="a" * 64,
            received_at=received_at,
        ))


def test_floor_window_uses_utc_boundaries():
    value = datetime(2026, 11, 28, 12, 29, tzinfo=timezone.utc)
    assert floor_window(value, timedelta(minutes=15)) == datetime(2026, 11, 28, 12, 15, tzinfo=timezone.utc)
    assert floor_window(value, timedelta(days=1)) == datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc)


def test_aggregation_is_idempotent_and_store_scoped(db_factory):
    now = datetime(2026, 11, 28, 12, 40, tzinfo=timezone.utc)
    event_at = datetime(2026, 11, 28, 12, 20, tzinfo=timezone.utc)
    _add_inbox(db_factory, 1, "DEVICE_HEARTBEAT", event_at, 1)
    _add_inbox(db_factory, 1, "DEVICE_HEARTBEAT", event_at + timedelta(seconds=1), 2)
    _add_inbox(db_factory, 2, "DEVICE_HEARTBEAT", event_at, 1)
    # Start the bounded backfill immediately before the window under test.
    with db_factory.begin() as db:
        db.add(models.EdgeObservabilityCheckpoint(
            job_name="edge-observability-15m-v1",
            last_completed_window=event_at + timedelta(minutes=60),
            updated_at=now,
        ))
    aggregate_cycle(db_factory, now=now, max_windows_per_granularity=1000)
    aggregate_cycle(db_factory, now=now, max_windows_per_granularity=1000)
    with db_factory() as db:
        rows = db.scalars(select(models.EdgeObservabilityAggregate)).all()
        found = {(r.store_id, r.granularity, r.dimension_value): r.value_count for r in rows
                 if r.window_start == datetime(2026, 11, 28, 12, 15, tzinfo=timezone.utc)}
        assert found[(1, "15m", "DEVICE_HEARTBEAT")] == 2
        assert found[(1, "15m", "ALL")] == 2
        assert found[(2, "15m", "ALL")] == 1
        assert len(rows) == len({(r.store_id, r.granularity, r.window_start, r.metric_name, r.dimension_value) for r in rows})


def test_checkpoint_naive_timestamp_is_interpreted_as_utc(db_factory):
    now = datetime(2026, 11, 28, 12, 40, tzinfo=timezone.utc)
    with db_factory.begin() as db:
        db.add(models.EdgeObservabilityCheckpoint(
            job_name="edge-observability-15m-v1",
            last_completed_window=datetime(2026, 11, 28, 12, 15),
            updated_at=now,
        ))
    result = aggregate_cycle(db_factory, now=now, max_windows_per_granularity=1)
    assert result["15m"] == 1


def test_retention_only_deletes_observability_rows(db_factory):
    now = datetime(2026, 11, 28, tzinfo=timezone.utc)
    with db_factory.begin() as db:
        db.add(models.EdgeSupervisorEvent(
            event_key="a" * 64, supervisor_instance_id="supervisor-1",
            event_type="STOPPED", restart_count=0,
            occurred_at=now - timedelta(days=91),
        ))
        db.add(models.EdgeObservabilityAggregate(
            store_id=1, granularity="daily", window_start=now - timedelta(days=91),
            metric_name="events_received", dimension_value="ALL", value_count=1,
        ))
        db.add(models.EdgeDevice(
            device_id="keep-device", store_id=1, device_type="gateway", status="ACTIVE",
        ))
    deleted = purge_expired(db_factory, now=now, batch_size=1)
    assert deleted == {"aggregates": 1, "supervisor_events": 1}
    with db_factory() as db:
        assert db.get(models.EdgeDevice, "keep-device") is not None
        assert db.scalar(select(models.EdgeObservabilityAggregate.id)) is None
        assert db.scalar(select(models.EdgeSupervisorEvent.id)) is None
