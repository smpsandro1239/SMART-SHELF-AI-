"""SQLite migration coverage for Edge task assignments and task revisions."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


MIGRATION = "0102_edge_task_assignments.py"


def _load_migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / MIGRATION
    spec = importlib.util.spec_from_file_location("edge_task_assignments", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _apply(migration, connection, operation="upgrade"):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration, operation)()


def test_edge_task_assignment_migration_enforces_history_tenant_and_revision(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'edge-task-assignment.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY)")
        db.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        db.exec_driver_sql(
            "CREATE TABLE replenishment_tasks (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)"
        )
        db.exec_driver_sql(
            "CREATE TABLE edge_devices (device_id VARCHAR(120) PRIMARY KEY, store_id INTEGER NOT NULL)"
        )
        db.exec_driver_sql("INSERT INTO stores (id) VALUES (1), (2)")
        db.exec_driver_sql("INSERT INTO users (id) VALUES (10)")
        db.exec_driver_sql(
            "INSERT INTO replenishment_tasks (id, store_id) VALUES (100, 1)"
        )
        db.exec_driver_sql(
            "INSERT INTO edge_devices (device_id, store_id) VALUES ('camera-a', 1), ('camera-b', 2)"
        )

        migration = _load_migration()
        _apply(migration, db)

        assert db.exec_driver_sql(
            "SELECT task_version FROM replenishment_tasks WHERE id=100"
        ).scalar_one() == 1

        db.exec_driver_sql(
            """
            INSERT INTO edge_device_task_assignments
                (id, store_id, device_id, task_id, task_version, valid_from,
                 valid_until, created_by_user_id, created_at)
            VALUES (1, 1, 'camera-a', 100, 1, '2026-11-26T10:00:00+00:00',
                    '2026-11-26T12:00:00+00:00', 10, '2026-11-26T10:00:00+00:00')
            """
        )
        db.exec_driver_sql(
            """
            INSERT INTO edge_device_task_assignment_events
                (id, assignment_id, event_type, actor_user_id, reason, created_at)
            VALUES (1, 1, 'CREATED', 10, 'Atribuição operacional aprovada',
                    '2026-11-26T10:00:00+00:00')
            """
        )

        # Every persisted task mutation advances the DB-owned revision exactly once.
        db.exec_driver_sql("UPDATE replenishment_tasks SET store_id=1 WHERE id=100")
        assert db.exec_driver_sql(
            "SELECT task_version FROM replenishment_tasks WHERE id=100"
        ).scalar_one() == 2

        # A caller cannot forge or skip the revision counter.
        db.exec_driver_sql(
            "UPDATE replenishment_tasks SET task_version=99 WHERE id=100"
        )
        assert db.exec_driver_sql(
            "SELECT task_version FROM replenishment_tasks WHERE id=100"
        ).scalar_one() == 3

        # Composite tenant lineage prevents cross-store device/task bindings.
        with pytest.raises(IntegrityError):
            db.exec_driver_sql(
                """
                INSERT INTO edge_device_task_assignments
                    (id, store_id, device_id, task_id, task_version, valid_from,
                     created_by_user_id, created_at)
                VALUES (2, 2, 'camera-a', 100, 3, '2026-11-26T10:00:00+00:00',
                        10, '2026-11-26T10:00:00+00:00')
                """
            )

        # One non-revoked assignment per device/task pair.
        with pytest.raises(IntegrityError):
            db.exec_driver_sql(
                """
                INSERT INTO edge_device_task_assignments
                    (id, store_id, device_id, task_id, task_version, valid_from,
                     created_by_user_id, created_at)
                VALUES (3, 1, 'camera-a', 100, 3, '2026-11-26T10:00:00+00:00',
                        10, '2026-11-26T10:00:00+00:00')
                """
            )

        # Assignment identity and creation facts cannot be rewritten.
        with pytest.raises(IntegrityError, match="assignment identity is immutable"):
            db.exec_driver_sql(
                "UPDATE edge_device_task_assignments SET task_id=100 WHERE id=1"
            )
        with pytest.raises(IntegrityError, match="assignment history is append-only"):
            db.exec_driver_sql("DELETE FROM edge_device_task_assignments WHERE id=1")

        # Revocation closes the association once and records a separate immutable event.
        db.exec_driver_sql(
            """
            UPDATE edge_device_task_assignments
            SET revoked_at='2026-11-26T11:00:00+00:00',
                revoked_by_user_id=10,
                revocation_reason='Dispositivo substituído'
            WHERE id=1
            """
        )
        db.exec_driver_sql(
            """
            INSERT INTO edge_device_task_assignment_events
                (id, assignment_id, event_type, actor_user_id, reason, created_at)
            VALUES (2, 1, 'REVOKED', 10, 'Dispositivo substituído',
                    '2026-11-26T11:00:00+00:00')
            """
        )
        with pytest.raises(IntegrityError, match="assignment revocation is immutable"):
            db.exec_driver_sql(
                "UPDATE edge_device_task_assignments SET revoked_at='2026-11-26T11:30:00+00:00' WHERE id=1"
            )
        with pytest.raises(IntegrityError, match="assignment events are append-only"):
            db.exec_driver_sql(
                "UPDATE edge_device_task_assignment_events SET reason='alterado' WHERE id=1"
            )
        with pytest.raises(IntegrityError, match="assignment events are append-only"):
            db.exec_driver_sql(
                "DELETE FROM edge_device_task_assignment_events WHERE id=1"
            )

        # A replacement assignment can be created after the previous one is revoked.
        db.exec_driver_sql(
            """
            INSERT INTO edge_device_task_assignments
                (id, store_id, device_id, task_id, task_version, valid_from,
                 created_by_user_id, created_at)
            VALUES (4, 1, 'camera-a', 100, 3, '2026-11-26T11:01:00+00:00',
                    10, '2026-11-26T11:01:00+00:00')
            """
        )

        _apply(migration, db, "downgrade")
        tables = {
            row[0] for row in db.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "edge_device_task_assignments" not in tables
        assert "edge_device_task_assignment_events" not in tables
        columns = {
            row[1] for row in db.exec_driver_sql("PRAGMA table_info(replenishment_tasks)")
        }
        assert "task_version" not in columns

    engine.dispose()
