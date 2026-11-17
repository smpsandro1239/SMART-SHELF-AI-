"""Database-level lineage and stock-conservation checks for inventory movements."""

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
        / "0052_inventory_movement_lineage_guard.py"
    )
    spec = importlib.util.spec_from_file_location("inventory_movement_lineage_guard", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_sqlite_movement_guard_enforces_tenant_lineage_and_quantity_conservation(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'movement-lineage.db'}")

    with engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TABLE replenishment_tasks (
                id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL, status TEXT NOT NULL,
                actual_quantity NUMERIC, completed_at TEXT
            )
        """)
        connection.exec_driver_sql("""
            CREATE TABLE inventory_snapshots (
                id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL, on_hand_quantity NUMERIC NOT NULL,
                reserved_quantity NUMERIC NOT NULL, source TEXT NOT NULL,
                external_reference TEXT, captured_at TEXT NOT NULL
            )
        """)
        connection.exec_driver_sql("""
            CREATE TABLE inventory_movements (
                id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL,
                store_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
                quantity NUMERIC NOT NULL, source_snapshot_id INTEGER NOT NULL,
                result_snapshot_id INTEGER NOT NULL
            )
        """)
        connection.exec_driver_sql("""
            INSERT INTO replenishment_tasks
                (id, store_id, product_id, status, actual_quantity, completed_at)
            VALUES (1, 10, 100, 'COMPLETED', 4, '2026-01-01 10:00:00')
        """)
        connection.exec_driver_sql("""
            INSERT INTO inventory_snapshots
                (id, store_id, product_id, on_hand_quantity, reserved_quantity,
                 source, external_reference, captured_at)
            VALUES
                (1, 10, 100, 20, 2, 'ERP', 'ERP-1', '2026-01-01 09:00:00'),
                (2, 10, 100, 16, 2, 'MANUAL', 'TASK-RECONCILIATION-1',
                 '2026-01-01 10:01:00'),
                (3, 20, 100, 16, 2, 'MANUAL', 'TASK-RECONCILIATION-1',
                 '2026-01-01 10:01:00'),
                (4, 10, 100, 15, 2, 'MANUAL', 'TASK-RECONCILIATION-1',
                 '2026-01-01 10:01:00')
        """)

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        connection.exec_driver_sql("""
            INSERT INTO inventory_movements
                (id, task_id, store_id, product_id, quantity,
                 source_snapshot_id, result_snapshot_id)
            VALUES (1, 1, 10, 100, 4, 1, 2)
        """)

        with pytest.raises(IntegrityError, match="inventory movement lineage"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_movements
                    (id, task_id, store_id, product_id, quantity,
                     source_snapshot_id, result_snapshot_id)
                VALUES (2, 1, 20, 100, 4, 1, 3)
            """)

        with pytest.raises(IntegrityError, match="inventory movement lineage"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_movements
                    (id, task_id, store_id, product_id, quantity,
                     source_snapshot_id, result_snapshot_id)
                VALUES (3, 1, 10, 100, 4, 1, 4)
            """)

        count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM inventory_movements"
        ).scalar_one()
        assert count == 1

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

    engine.dispose()
