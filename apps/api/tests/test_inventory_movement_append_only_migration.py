"""SQLite migration contract for append-only inventory movement evidence."""

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
        / "0053_inventory_movement_append_only.py"
    )
    spec = importlib.util.spec_from_file_location("inventory_movement_append_only", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_inventory_movements_are_append_only_and_downgrade_removes_guards(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'movement-append-only.db'}")

    with engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TABLE inventory_movements (
                id INTEGER PRIMARY KEY,
                task_id INTEGER NOT NULL,
                quantity NUMERIC NOT NULL,
                reason TEXT NOT NULL
            )
        """)
        connection.exec_driver_sql("""
            INSERT INTO inventory_movements (id, task_id, quantity, reason)
            VALUES (1, 10, 4, 'approved reconciliation')
        """)

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        with pytest.raises(IntegrityError, match="inventory_movements is append-only"):
            connection.exec_driver_sql(
                "UPDATE inventory_movements SET quantity = 99 WHERE id = 1"
            )

        with pytest.raises(IntegrityError, match="inventory_movements is append-only"):
            connection.exec_driver_sql("DELETE FROM inventory_movements WHERE id = 1")

        row = connection.exec_driver_sql(
            "SELECT quantity, reason FROM inventory_movements WHERE id = 1"
        ).one()
        assert row == (4, "approved reconciliation")

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        connection.exec_driver_sql(
            "UPDATE inventory_movements SET reason = 'after downgrade' WHERE id = 1"
        )
        connection.exec_driver_sql("DELETE FROM inventory_movements WHERE id = 1")
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM inventory_movements"
        ).scalar_one() == 0

    engine.dispose()
