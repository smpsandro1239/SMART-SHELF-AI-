"""SQLite tests for immutable replenishment task identity and audit history."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_task_identity_and_audit_events_are_protected_after_audit_begins(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0097_replenishment_task_audit_immutability.py"
    spec = importlib.util.spec_from_file_location("replenishment_task_audit_immutability", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'task-audit-immutability.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE replenishment_tasks (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, shelf_id INTEGER NOT NULL, product_id INTEGER NOT NULL, status TEXT NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE replenishment_task_events (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, event_type TEXT NOT NULL, reason TEXT)")
        connection.exec_driver_sql("INSERT INTO replenishment_tasks (id, store_id, shelf_id, product_id, status) VALUES (1, 10, 100, 1000, 'PENDING'), (2, 10, 200, 1000, 'PENDING')")
        connection.exec_driver_sql("INSERT INTO replenishment_task_events (id, task_id, event_type, reason) VALUES (1, 1, 'CREATED', 'Task created')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        connection.exec_driver_sql("UPDATE replenishment_tasks SET status='COMPLETED' WHERE id=1")
        with pytest.raises(IntegrityError, match="replenishment task identity is immutable"):
            connection.exec_driver_sql("UPDATE replenishment_tasks SET shelf_id=200 WHERE id=1")
        with pytest.raises(IntegrityError, match="replenishment task has audit history"):
            connection.exec_driver_sql("DELETE FROM replenishment_tasks WHERE id=1")
        with pytest.raises(IntegrityError, match="replenishment task events are append-only"):
            connection.exec_driver_sql("UPDATE replenishment_task_events SET reason='tampered' WHERE id=1")
        with pytest.raises(IntegrityError, match="replenishment task events are append-only"):
            connection.exec_driver_sql("DELETE FROM replenishment_task_events WHERE id=1")

        connection.exec_driver_sql("UPDATE replenishment_tasks SET shelf_id=201 WHERE id=2")
        connection.exec_driver_sql("DELETE FROM replenishment_tasks WHERE id=2")
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM replenishment_task_events").scalar_one() == 1
        assert connection.exec_driver_sql("SELECT status FROM replenishment_tasks WHERE id=1").scalar_one() == "COMPLETED"

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
