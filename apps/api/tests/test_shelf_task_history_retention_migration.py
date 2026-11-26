"""Database guards that preserve replenishment task history on shelf/zone deletion."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_sqlite_shelf_and_zone_deletion_is_blocked_when_task_history_exists(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0096_shelf_task_history_retention_guard.py"
    spec = importlib.util.spec_from_file_location("shelf_task_history_retention_guard", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'shelf-task-retention.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE replenishment_tasks (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL)")
        connection.exec_driver_sql("INSERT INTO zones (id) VALUES (1), (2)")
        connection.exec_driver_sql("INSERT INTO shelves (id, zone_id) VALUES (10, 1), (20, 2)")
        connection.exec_driver_sql("INSERT INTO replenishment_tasks (id, shelf_id) VALUES (100, 10)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        with pytest.raises(IntegrityError, match="shelf has replenishment task history"):
            connection.exec_driver_sql("DELETE FROM shelves WHERE id=10")
        with pytest.raises(IntegrityError, match="zone has replenishment task history"):
            connection.exec_driver_sql("DELETE FROM zones WHERE id=1")
        connection.exec_driver_sql("DELETE FROM shelves WHERE id=20")
        connection.exec_driver_sql("DELETE FROM zones WHERE id=2")
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM replenishment_tasks").scalar_one() == 1
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM shelves WHERE id=10").scalar_one() == 1
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
