"""SQLite contract for the AVAILABLE WMS source requirement on new movements."""

import importlib.util
from pathlib import Path
from uuid import uuid4

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
        / "0088_inventory_movement_available_source_guard.py"
    )
    spec = importlib.util.spec_from_file_location("movement_available_source_guard", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _insert_movement(connection, *, movement_id: int, task_id: int, snapshot_id: int):
    connection.exec_driver_sql(
        """
        INSERT INTO inventory_movements (
            id, task_id, store_id, product_id, source_snapshot_id,
            operation_id, source_location_code, destination_shelf_id
        )
        VALUES (?, ?, 10, 100, ?, ?, 'BACKROOM-A', 20)
        """,
        (movement_id, task_id, snapshot_id, str(uuid4())),
    )


def test_new_movements_require_available_wms_snapshot_and_downgrade_restores_prior_guard(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'movement-available-source.db'}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE replenishment_tasks (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, product_id INTEGER NOT NULL, shelf_id INTEGER NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE inventory_snapshots (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, product_id INTEGER NOT NULL, source TEXT NOT NULL, location_code TEXT, availability_status TEXT)"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE inventory_movements (
                id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, store_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL, source_snapshot_id INTEGER NOT NULL,
                operation_id TEXT, source_location_code TEXT, destination_shelf_id INTEGER
            )
            """
        )
        connection.exec_driver_sql("INSERT INTO zones (id, store_id) VALUES (1, 10)")
        connection.exec_driver_sql("INSERT INTO shelves (id, zone_id) VALUES (20, 1)")
        connection.exec_driver_sql(
            "INSERT INTO replenishment_tasks (id, store_id, product_id, shelf_id) VALUES (30, 10, 100, 20), (31, 10, 100, 20), (32, 10, 100, 20)"
        )
        connection.exec_driver_sql(
            """
            INSERT INTO inventory_snapshots (id, store_id, product_id, source, location_code, availability_status)
            VALUES
                (40, 10, 100, 'WMS', 'BACKROOM-A', 'AVAILABLE'),
                (41, 10, 100, 'WMS', 'BACKROOM-A', 'UNAVAILABLE'),
                (42, 10, 100, 'WMS', 'BACKROOM-A', 'UNKNOWN')
            """
        )

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        _insert_movement(connection, movement_id=1, task_id=30, snapshot_id=40)

        with pytest.raises(IntegrityError, match="same-store physical provenance"):
            _insert_movement(connection, movement_id=2, task_id=31, snapshot_id=41)

        with pytest.raises(IntegrityError, match="same-store physical provenance"):
            _insert_movement(connection, movement_id=3, task_id=32, snapshot_id=42)

        # SQLite must enforce the same required provenance fields as PostgreSQL.
        with pytest.raises(IntegrityError, match="same-store physical provenance"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_movements
                    (id, task_id, store_id, product_id, source_snapshot_id,
                     operation_id, source_location_code, destination_shelf_id)
                VALUES (4, 31, 10, 100, 40, NULL, 'BACKROOM-A', 20)
            """)
        with pytest.raises(IntegrityError, match="same-store physical provenance"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_movements
                    (id, task_id, store_id, product_id, source_snapshot_id,
                     operation_id, source_location_code, destination_shelf_id)
                VALUES (5, 31, 10, 100, 40, ?, '   ', 20)
            """, (str(uuid4()),))
        with pytest.raises(IntegrityError, match="same-store physical provenance"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_movements
                    (id, task_id, store_id, product_id, source_snapshot_id,
                     operation_id, source_location_code, destination_shelf_id)
                VALUES (6, 31, 10, 100, 40, ?, 'BACKROOM-A', NULL)
            """, (str(uuid4()),))

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        # Downgrade restores the 0086 provenance contract; availability was
        # not part of that older contract and is therefore no longer checked.
        _insert_movement(connection, movement_id=4, task_id=31, snapshot_id=41)

    engine.dispose()
