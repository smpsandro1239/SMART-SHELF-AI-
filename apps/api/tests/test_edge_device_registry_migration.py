"""SQLite migration tests for the tenant-bound edge device registry (0071)."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _apply_migration(connection):
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0071_edge_device_registry.py"
    )
    spec = importlib.util.spec_from_file_location("edge_device_registry_0071", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    return migration


def _base_schema(connection):
    connection.exec_driver_sql(
        "CREATE TABLE stores (id INTEGER PRIMARY KEY, code VARCHAR(50) NOT NULL)"
    )
    connection.exec_driver_sql(
        "CREATE TABLE shelves (id INTEGER PRIMARY KEY, code VARCHAR(50) NOT NULL)"
    )
    connection.exec_driver_sql("INSERT INTO stores (id, code) VALUES (1, 'store-a')")
    connection.exec_driver_sql("INSERT INTO shelves (id, code) VALUES (10, 'shelf-a')")


def test_edge_registry_schema_enforces_identity_uniqueness_and_append_only_records(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'edge-device-registry.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        _base_schema(db)
        _apply_migration(db)
        now = "2026-11-23T10:00:00+00:00"
        db.exec_driver_sql(
            """
            INSERT INTO edge_devices
            (device_id, store_id, device_type, status, created_at)
            VALUES ('camera-a', 1, 'fixed_camera', 'ACTIVE', ?)
            """,
            (now,),
        )
        db.exec_driver_sql(
            """
            INSERT INTO edge_device_credentials
            (credential_id, device_id, secret_sha256, scopes, created_at, expires_at)
            VALUES ('a' || printf('%031d', 1), 'camera-a', ?, '["events:write"]', ?, ?)
            """,
            ("a" * 64, now, "2026-12-23T10:00:00+00:00"),
        )
        db.exec_driver_sql(
            """
            INSERT INTO edge_device_event_cursors (device_id, last_sequence, updated_at)
            VALUES ('camera-a', 0, ?)
            """,
            (now,),
        )
        db.exec_driver_sql(
            """
            INSERT INTO edge_device_event_inbox
            (device_id, event_id, sequence_number, event_type, store_id, shelf_id,
             occurred_at, payload, fingerprint_sha256, received_at)
            VALUES ('camera-a', '00000000-0000-0000-0000-000000000001', 1,
                    'DEVICE_HEARTBEAT', 1, NULL, ?, '{}', ?, ?)
            """,
            (now, "b" * 64, now),
        )
        db.exec_driver_sql(
            """
            INSERT INTO edge_device_audit_events
            (device_id, credential_id, event_type, details, created_at)
            VALUES ('camera-a', NULL, 'DEVICE_REGISTERED', '{}', ?)
            """,
            (now,),
        )

        with pytest.raises(IntegrityError, match="append-only"):
            db.exec_driver_sql(
                "UPDATE edge_device_event_inbox SET event_type='SHELF_CAPTURED' WHERE device_id='camera-a'"
            )
        with pytest.raises(IntegrityError, match="append-only"):
            db.exec_driver_sql("DELETE FROM edge_device_event_inbox WHERE device_id='camera-a'")
        with pytest.raises(IntegrityError, match="append-only"):
            db.exec_driver_sql(
                "UPDATE edge_device_audit_events SET event_type='DEVICE_DISABLED' WHERE id=1"
            )
        with pytest.raises(IntegrityError, match="immutable"):
            db.exec_driver_sql("UPDATE edge_devices SET store_id=2 WHERE device_id='camera-a'")
        with pytest.raises(IntegrityError, match="UNIQUE"):
            db.exec_driver_sql(
                """
                INSERT INTO edge_device_event_inbox
                (device_id, event_id, sequence_number, event_type, store_id, shelf_id,
                 occurred_at, payload, fingerprint_sha256, received_at)
                VALUES ('camera-a', '00000000-0000-0000-0000-000000000002', 1,
                        'DEVICE_HEARTBEAT', 1, NULL, ?, '{}', ?, ?)
                """,
                (now, "c" * 64, now),
            )
        assert db.exec_driver_sql(
            "SELECT COUNT(*) FROM edge_device_event_inbox"
        ).scalar_one() == 1
        assert db.exec_driver_sql(
            "SELECT COUNT(*) FROM edge_device_audit_events"
        ).scalar_one() == 1
    engine.dispose()


def test_edge_device_cursor_rejects_negative_sequences_and_invalid_device_types(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'edge-device-cursor.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        _base_schema(db)
        _apply_migration(db)
        now = "2026-11-23T10:00:00+00:00"
        with pytest.raises(IntegrityError, match="CHECK constraint"):
            db.exec_driver_sql(
                """
                INSERT INTO edge_devices
                (device_id, store_id, device_type, status, created_at)
                VALUES ('unknown-a', 1, 'unknown', 'ACTIVE', ?)
                """,
                (now,),
            )
        db.exec_driver_sql(
            """
            INSERT INTO edge_devices
            (device_id, store_id, device_type, status, created_at)
            VALUES ('camera-b', 1, 'fixed_camera', 'ACTIVE', ?)
            """,
            (now,),
        )
        with pytest.raises(IntegrityError, match="CHECK constraint"):
            db.exec_driver_sql(
                "INSERT INTO edge_device_event_cursors (device_id, last_sequence, updated_at) VALUES ('camera-b', -1, ?)",
                (now,),
            )
    engine.dispose()
