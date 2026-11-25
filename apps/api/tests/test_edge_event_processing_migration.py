"""SQLite migration coverage for durable Edge event processing state (0073)."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load(name):
    path = Path(__file__).parents[1] / "migrations" / "versions" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(module, connection, operation="upgrade"):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, operation)()


def test_edge_event_processing_migration_backfills_inbox_and_downgrades(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'edge-processing-migration.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY, code VARCHAR(50) NOT NULL)")
        db.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, code VARCHAR(50) NOT NULL)")
        db.exec_driver_sql("INSERT INTO stores (id, code) VALUES (1, 'store-a')")
        db.exec_driver_sql("INSERT INTO shelves (id, code) VALUES (10, 'shelf-a')")
        _apply(_load("0071_edge_device_registry.py"), db)
        _apply(_load("0072_edge_device_telemetry.py"), db)
        now = "2026-11-23T10:00:00+00:00"
        db.exec_driver_sql(
            "INSERT INTO edge_devices (device_id, store_id, device_type, status, created_at) "
            "VALUES ('camera-a', 1, 'fixed_camera', 'ACTIVE', ?)", (now,),
        )
        db.exec_driver_sql(
            """INSERT INTO edge_device_event_inbox
            (device_id, event_id, sequence_number, event_type, store_id, shelf_id,
             occurred_at, payload, fingerprint_sha256, received_at)
            VALUES ('camera-a', '00000000-0000-4000-8000-000000000001', 1,
                    'DEVICE_HEARTBEAT', 1, NULL, ?, '{}', ?, ?)""",
            (now, "a" * 64, now),
        )

        migration = _load("0073_edge_event_processing.py")
        _apply(migration, db)
        row = db.exec_driver_sql(
            "SELECT status, attempt_count, max_attempts, available_at "
            "FROM edge_device_event_processing WHERE inbox_id=1"
        ).one()
        assert row.status == "PENDING"
        assert row.attempt_count == 0
        assert row.max_attempts == 8

        with pytest.raises(IntegrityError, match="CHECK constraint"):
            db.exec_driver_sql(
                """INSERT INTO edge_device_event_processing
                (inbox_id, status, attempt_count, max_attempts, available_at,
                 fencing_token, created_at, updated_at)
                VALUES (1, 'UNKNOWN', 0, 8, ?, 0, ?, ?)""",
                (now, now, now),
            )
        with pytest.raises(IntegrityError, match="CHECK constraint"):
            db.exec_driver_sql(
                """INSERT INTO edge_device_event_processing
                (inbox_id, status, attempt_count, max_attempts, available_at,
                 lease_owner, lease_expires_at, fencing_token, created_at, updated_at)
                VALUES (1, 'PROCESSING', 1, 8, ?, NULL, ?, 1, ?, ?)""",
                (now, now, now, now),
            )
        _apply(migration, db, "downgrade")
        tables = {
            row[0] for row in db.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "edge_device_event_processing" not in tables
        assert db.exec_driver_sql("SELECT COUNT(*) FROM edge_device_event_inbox").scalar_one() == 1
    engine.dispose()
