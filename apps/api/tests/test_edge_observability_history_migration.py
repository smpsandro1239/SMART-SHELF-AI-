"""SQLite coverage for the Edge observability history schema."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0105_edge_observability_history.py"
    spec = importlib.util.spec_from_file_location("edge_observability_0105", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _apply(migration, connection, operation="upgrade"):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration, operation)()


def test_observability_schema_enforces_store_scope_idempotency_and_allowlists(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'edge-observability.db'}")
    migration = _load_migration()
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY)")
        db.exec_driver_sql("INSERT INTO stores (id) VALUES (1), (2)")
        _apply(migration, db)

        insert_aggregate = """
            INSERT INTO edge_observability_aggregates
            (store_id, granularity, window_start, metric_name, dimension_value, value_count)
            VALUES (1, '15m', '2026-11-28T00:00:00+00:00', 'events_received', 'DEVICE_HEARTBEAT', 3)
        """
        db.exec_driver_sql(insert_aggregate)
        with pytest.raises(IntegrityError):
            db.exec_driver_sql(insert_aggregate)
        with pytest.raises(IntegrityError):
            db.exec_driver_sql(insert_aggregate.replace("'15m'", "'hourly'"))
        with pytest.raises(IntegrityError):
            db.exec_driver_sql(insert_aggregate.replace("'events_received'", "'authentication_rejected'"))
        with pytest.raises(IntegrityError):
            db.exec_driver_sql(insert_aggregate.replace("VALUES (1,", "VALUES (99,"))

        db.exec_driver_sql("""
            INSERT INTO edge_supervisor_events
            (event_key, supervisor_instance_id, event_type, worker_id, reason_code, restart_count, occurred_at)
            VALUES ('event-0001', 'supervisor-a', 'RESTARTING', 'edge-worker-a', 'CHILD_EXITED', 1,
                    '2026-11-28T00:00:00+00:00')
        """)
        with pytest.raises(IntegrityError):
            db.exec_driver_sql("""
                INSERT INTO edge_supervisor_events
                (event_key, supervisor_instance_id, event_type, restart_count, occurred_at)
                VALUES ('event-0002', 'supervisor-a', 'UNSAFE_PAYLOAD', 0, '2026-11-28T00:00:00+00:00')
            """)
        with pytest.raises(IntegrityError):
            db.exec_driver_sql("""
                INSERT INTO edge_supervisor_events
                (event_key, supervisor_instance_id, event_type, restart_count, occurred_at)
                VALUES ('event-0001', 'supervisor-a', 'FAILED', 0, '2026-11-28T00:00:00+00:00')
            """)

        _apply(migration, db, "downgrade")
    engine.dispose()
