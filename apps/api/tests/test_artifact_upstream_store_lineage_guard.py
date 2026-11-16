"""Prevent moving upstream shelf hierarchy across tenants after artifacts exist."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0049_artifact_upstream_store_lineage_guard.py"
    spec = importlib.util.spec_from_file_location("artifact_upstream_store_lineage_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(connection):
    connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE shelf_images (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE shelf_image_artifact_references (id INTEGER PRIMARY KEY, shelf_image_id INTEGER NOT NULL, store_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE shelf_image_artifact_inventory_snapshots (id INTEGER PRIMARY KEY, shelf_image_id INTEGER NOT NULL, store_id INTEGER NOT NULL)")
    connection.exec_driver_sql("INSERT INTO zones VALUES (1, 10), (2, 20)")
    connection.exec_driver_sql("INSERT INTO shelves VALUES (11, 1), (22, 2)")
    connection.exec_driver_sql("INSERT INTO shelf_images VALUES (111, 11), (222, 22)")
    connection.exec_driver_sql("INSERT INTO shelf_image_artifact_references VALUES (1, 111, 10)")
    connection.exec_driver_sql("INSERT INTO shelf_image_artifact_inventory_snapshots VALUES (1, 111, 10)")


def test_cannot_move_zone_shelf_or_image_across_stores_with_artifact_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'upstream-lineage.db'}")
    with engine.begin() as connection:
        _schema(connection)
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        with pytest.raises(IntegrityError, match="cannot move zone across stores"):
            connection.exec_driver_sql("UPDATE zones SET store_id = 20 WHERE id = 1")
        with pytest.raises(sqlite3.IntegrityError, match="cannot move shelf across stores"):
            connection.exec_driver_sql("UPDATE shelves SET zone_id = 22 WHERE id = 11")
        with pytest.raises(sqlite3.IntegrityError, match="cannot move image across stores"):
            connection.exec_driver_sql("UPDATE shelf_images SET shelf_id = 22 WHERE id = 111")
        # Same-tenant metadata changes and no-op assignments remain allowed.
        connection.exec_driver_sql("UPDATE zones SET store_id = 10 WHERE id = 1")
        connection.exec_driver_sql("UPDATE shelves SET zone_id = 1 WHERE id = 11")
        connection.exec_driver_sql("UPDATE shelf_images SET shelf_id = 11 WHERE id = 111")
        with Operations.context(MigrationContext.configure(connection)):
            _migration().downgrade()
        connection.exec_driver_sql("UPDATE shelf_images SET shelf_id = 22 WHERE id = 111")
    engine.dispose()


def test_upstream_move_is_allowed_when_no_artifact_history_exists(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'upstream-lineage-empty.db'}")
    with engine.begin() as connection:
        _schema(connection)
        connection.exec_driver_sql("DELETE FROM shelf_image_artifact_references")
        connection.exec_driver_sql("DELETE FROM shelf_image_artifact_inventory_snapshots")
        with Operations.context(MigrationContext.configure(connection)):
            _migration().upgrade()
        connection.exec_driver_sql("UPDATE shelf_images SET shelf_id = 22 WHERE id = 111")
        connection.exec_driver_sql("UPDATE shelves SET zone_id = 2 WHERE id = 11")
        connection.exec_driver_sql("UPDATE zones SET store_id = 20 WHERE id = 1")
    engine.dispose()
