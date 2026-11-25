"""SQLite contract for frozen product base units on inventory movements."""

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
        / "0089_inventory_movement_base_unit_snapshot.py"
    )
    spec = importlib.util.spec_from_file_location("movement_base_unit_snapshot", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _insert(connection, movement_id: int, unit_code: str | None):
    connection.exec_driver_sql(
        """
        INSERT INTO inventory_movements (
            id, task_id, store_id, product_id, source_snapshot_id, unit_code
        )
        VALUES (?, ?, 10, 100, 40, ?)
        """,
        (movement_id, movement_id + 100, unit_code),
    )


def test_new_movements_freeze_product_base_unit_without_inventing_historical_units(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'movement-base-unit.db'}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE products (id INTEGER PRIMARY KEY, unit TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE inventory_movements (
                id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, store_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL, source_snapshot_id INTEGER NOT NULL
            )
            """
        )
        connection.exec_driver_sql("INSERT INTO products (id, unit) VALUES (100, 'kg')")
        connection.exec_driver_sql(
            "INSERT INTO inventory_movements (id, task_id, store_id, product_id, source_snapshot_id) VALUES (1, 101, 10, 100, 40)"
        )

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        historical = connection.exec_driver_sql(
            "SELECT unit_code FROM inventory_movements WHERE id = 1"
        ).scalar_one()
        assert historical is None

        _insert(connection, movement_id=2, unit_code="kg")

        with pytest.raises(IntegrityError, match="match the product base unit"):
            _insert(connection, movement_id=3, unit_code="un")

        with pytest.raises(IntegrityError, match="match the product base unit"):
            _insert(connection, movement_id=4, unit_code="   ")

        with pytest.raises(IntegrityError, match="match the product base unit"):
            _insert(connection, movement_id=5, unit_code=None)

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        columns = {
            row[1] for row in connection.exec_driver_sql(
                "PRAGMA table_info(inventory_movements)"
            ).all()
        }
        assert "unit_code" not in columns

    engine.dispose()
