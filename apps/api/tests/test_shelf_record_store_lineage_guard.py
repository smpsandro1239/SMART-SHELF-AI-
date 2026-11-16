"""Database-level tenant lineage for shelf-scoped operational records."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0050_shelf_record_store_lineage_guard.py"
    spec = importlib.util.spec_from_file_location("shelf_record_store_lineage_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(connection):
    connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE observation_alerts (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL, store_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE capture_sessions (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL, store_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE replenishment_tasks (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL, store_id INTEGER NOT NULL)")
    connection.exec_driver_sql("INSERT INTO zones VALUES (1, 10), (2, 20)")
    connection.exec_driver_sql("INSERT INTO shelves VALUES (11, 1), (22, 2)")


def test_shelf_scoped_records_require_the_shelf_tenant_and_block_upstream_moves(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'shelf-record-lineage.db'}")
    with engine.begin() as connection:
        _schema(connection)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()

        for table in ("observation_alerts", "capture_sessions", "replenishment_tasks"):
            connection.exec_driver_sql(f"INSERT INTO {table} VALUES (1, 11, 10)")
            with pytest.raises(IntegrityError, match="shelf record store"):
                connection.exec_driver_sql(f"INSERT INTO {table} VALUES (2, 11, 20)")
            with pytest.raises(IntegrityError, match="shelf record store"):
                connection.exec_driver_sql(f"UPDATE {table} SET store_id = 20 WHERE id = 1")

        with pytest.raises(IntegrityError, match="cannot move shelf hierarchy"):
            connection.exec_driver_sql("UPDATE shelves SET zone_id = 22 WHERE id = 11")
        with pytest.raises(IntegrityError, match="cannot move shelf hierarchy"):
            connection.exec_driver_sql("UPDATE zones SET store_id = 20 WHERE id = 1")

        # Same-tenant assignments are harmless.
        connection.exec_driver_sql("UPDATE shelves SET zone_id = 1 WHERE id = 11")
        connection.exec_driver_sql("UPDATE zones SET store_id = 10 WHERE id = 1")

        with Operations.context(MigrationContext.configure(connection)):
            _migration().downgrade()
        connection.exec_driver_sql("UPDATE shelves SET zone_id = 2 WHERE id = 11")
    engine.dispose()


def test_shelf_scoped_record_migration_rejects_existing_cross_tenant_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'shelf-record-lineage-invalid.db'}")
    with engine.begin() as connection:
        _schema(connection)
        connection.exec_driver_sql("INSERT INTO replenishment_tasks VALUES (1, 11, 20)")
        with pytest.raises(RuntimeError, match="persisted records have mismatched stores"):
            with Operations.context(MigrationContext.configure(connection)):
                _migration().upgrade()
    engine.dispose()


def test_shelf_hierarchy_can_move_when_no_shelf_scoped_records_exist(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'shelf-record-lineage-empty.db'}")
    with engine.begin() as connection:
        _schema(connection)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        connection.exec_driver_sql("UPDATE shelves SET zone_id = 2 WHERE id = 11")
        connection.exec_driver_sql("UPDATE zones SET store_id = 20 WHERE id = 1")
    engine.dispose()
