"""SQLite migration coverage for the Edge task acknowledgement append-only ledger."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0103_edge_task_acknowledgements.py"
    )
    spec = importlib.util.spec_from_file_location(
        "edge_task_acknowledgements_migration", path
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _apply(migration, connection, operation="upgrade"):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration, operation)()


def test_sqlite_acknowledgement_migration_enforces_append_only_triggers(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'edge-acknowledgements.db'}")
    migration = _load_migration()

    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY)")
        db.exec_driver_sql(
            """
            CREATE TABLE edge_device_task_assignments (
                id INTEGER PRIMARY KEY,
                device_id VARCHAR(120) NOT NULL,
                task_id INTEGER NOT NULL,
                store_id INTEGER NOT NULL,
                task_version INTEGER NOT NULL,
                UNIQUE (id, device_id, task_id, store_id, task_version)
            )
            """
        )
        db.exec_driver_sql(
            """
            CREATE TABLE edge_device_event_inbox (
                id INTEGER PRIMARY KEY,
                device_id VARCHAR(120) NOT NULL,
                event_id VARCHAR(36) NOT NULL,
                UNIQUE (device_id, event_id)
            )
            """
        )
        db.exec_driver_sql("INSERT INTO stores (id) VALUES (1)")
        db.exec_driver_sql(
            """
            INSERT INTO edge_device_task_assignments
                (id, device_id, task_id, store_id, task_version)
            VALUES (10, 'edge-ack-device', 20, 1, 3)
            """
        )
        db.exec_driver_sql(
            """
            INSERT INTO edge_device_event_inbox (id, device_id, event_id)
            VALUES (30, 'edge-ack-device', '00000000-0000-4000-8000-000000000103')
            """
        )

        _apply(migration, db)
        db.exec_driver_sql(
            """
            INSERT INTO edge_task_acknowledgements
                (id, store_id, task_id, task_version, device_id, assignment_id,
                 inbox_id, event_id, sequence_number, fingerprint_sha256,
                 action, result, declared_at, received_at)
            VALUES
                (40, 1, 20, 3, 'edge-ack-device', 10, 30,
                 '00000000-0000-4000-8000-000000000103', 7, ?, 'COMPLETED',
                 'REVIEW_REQUIRED', '2026-11-27T06:00:00+00:00',
                 '2026-11-27T06:00:01+00:00')
            """,
            ("a" * 64,),
        )

        with pytest.raises(IntegrityError, match="Edge task acknowledgements are append-only"):
            db.exec_driver_sql(
                "UPDATE edge_task_acknowledgements SET result='ACCEPTED' WHERE id=40"
            )
        with pytest.raises(IntegrityError, match="Edge task acknowledgements are append-only"):
            db.exec_driver_sql(
                "DELETE FROM edge_task_acknowledgements WHERE id=40"
            )

        row = db.exec_driver_sql(
            "SELECT action, result, fingerprint_sha256 "
            "FROM edge_task_acknowledgements WHERE id=40"
        ).one()
        assert row.action == "COMPLETED"
        assert row.result == "REVIEW_REQUIRED"
        assert row.fingerprint_sha256 == "a" * 64

        # The migration's own downgrade removes both guards and the ledger.
        _apply(migration, db, "downgrade")
        tables = {
            row[0]
            for row in db.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "edge_task_acknowledgements" not in tables
        db.exec_driver_sql(
            """
            UPDATE edge_device_task_assignments
            SET task_version=4
            WHERE id=10
            """
        )

    engine.dispose()
