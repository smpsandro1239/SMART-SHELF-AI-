"""Database-level tenant lineage guards for external artifact records."""

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
        / "0048_artifact_store_lineage_guard.py"
    )
    spec = importlib.util.spec_from_file_location("artifact_store_lineage_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_minimal_schema(connection):
    connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE shelf_images (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL)")
    connection.exec_driver_sql("""
        CREATE TABLE shelf_image_artifact_references (
            id INTEGER PRIMARY KEY, shelf_image_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL, parent_reference_id INTEGER
        )
    """)
    connection.exec_driver_sql("""
        CREATE TABLE shelf_image_artifact_inventory_snapshots (
            id INTEGER PRIMARY KEY, shelf_image_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL
        )
    """)
    connection.exec_driver_sql("INSERT INTO zones (id, store_id) VALUES (1, 10), (2, 20)")
    connection.exec_driver_sql("INSERT INTO shelves (id, zone_id) VALUES (11, 1), (22, 2)")
    connection.exec_driver_sql("INSERT INTO shelf_images (id, shelf_id) VALUES (111, 11), (222, 22)")


def test_sqlite_artifact_records_must_match_the_store_of_their_image(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'artifact-store-lineage.db'}")
    with engine.begin() as connection:
        _create_minimal_schema(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        connection.exec_driver_sql(
            "INSERT INTO shelf_image_artifact_references "
            "(id, shelf_image_id, store_id) VALUES (1, 111, 10)"
        )
        connection.exec_driver_sql(
            "INSERT INTO shelf_image_artifact_inventory_snapshots "
            "(id, shelf_image_id, store_id) VALUES (1, 222, 20)"
        )

        with pytest.raises(IntegrityError, match="artifact store does not match shelf image store"):
            connection.exec_driver_sql(
                "INSERT INTO shelf_image_artifact_references "
                "(id, shelf_image_id, store_id) VALUES (2, 111, 20)"
            )
        with pytest.raises(IntegrityError, match="artifact store does not match shelf image store"):
            connection.exec_driver_sql(
                "INSERT INTO shelf_image_artifact_inventory_snapshots "
                "(id, shelf_image_id, store_id) VALUES (2, 222, 10)"
            )
        with pytest.raises(IntegrityError, match="artifact store does not match shelf image store"):
            connection.exec_driver_sql(
                "UPDATE shelf_image_artifact_references SET store_id = 20 WHERE id = 1"
            )
        with pytest.raises(IntegrityError, match="artifact store does not match shelf image store"):
            connection.exec_driver_sql(
                "UPDATE shelf_image_artifact_inventory_snapshots SET shelf_image_id = 111 WHERE id = 1"
            )

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        connection.exec_driver_sql(
            "INSERT INTO shelf_image_artifact_references "
            "(id, shelf_image_id, store_id) VALUES (3, 111, 20)"
        )
    engine.dispose()


def test_sqlite_migration_refuses_to_install_over_existing_cross_store_rows(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'artifact-store-lineage-invalid.db'}")
    with engine.begin() as connection:
        _create_minimal_schema(connection)
        connection.exec_driver_sql(
            "INSERT INTO shelf_image_artifact_references "
            "(id, shelf_image_id, store_id) VALUES (1, 111, 20)"
        )
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="persisted artifact records have mismatched stores"):
                migration.upgrade()
    engine.dispose()
