"""SQLite migration contract for append-only operational inventory snapshots."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load_migration():
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0051_inventory_snapshot_immutable.py"
    )
    spec = importlib.util.spec_from_file_location(
        "inventory_snapshot_immutable_migration", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_sqlite_inventory_snapshot_migration_blocks_update_and_delete(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'inventory-immutable.db'}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE inventory_snapshots (
                id INTEGER PRIMARY KEY,
                on_hand_quantity NUMERIC NOT NULL,
                reserved_quantity NUMERIC NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO inventory_snapshots "
            "(id, on_hand_quantity, reserved_quantity) VALUES (1, 12, 2)"
        )

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        with pytest.raises(IntegrityError, match="inventory_snapshots is append-only"):
            connection.exec_driver_sql(
                "UPDATE inventory_snapshots SET on_hand_quantity = 0 WHERE id = 1"
            )
        with pytest.raises(IntegrityError, match="inventory_snapshots is append-only"):
            connection.exec_driver_sql(
                "DELETE FROM inventory_snapshots WHERE id = 1"
            )

        row = connection.exec_driver_sql(
            "SELECT on_hand_quantity, reserved_quantity "
            "FROM inventory_snapshots WHERE id = 1"
        ).one()
        assert float(row.on_hand_quantity) == 12
        assert float(row.reserved_quantity) == 2

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        connection.exec_driver_sql(
            "UPDATE inventory_snapshots SET on_hand_quantity = 10 WHERE id = 1"
        )
        updated_quantity = connection.exec_driver_sql(
            "SELECT on_hand_quantity FROM inventory_snapshots WHERE id = 1"
        ).scalar_one()
        assert float(updated_quantity) == 10

    engine.dispose()
