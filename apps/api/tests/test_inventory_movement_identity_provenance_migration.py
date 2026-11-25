"""SQLite contract for movement identity backfill and provenance guards."""
import importlib.util
from pathlib import Path
from uuid import UUID

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
        / "0086_inventory_movement_identity_provenance.py"
    )
    spec = importlib.util.spec_from_file_location("movement_identity_provenance", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_backfills_identity_and_preserves_unknown_historical_provenance(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'movement-identity.db'}")

    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL, code TEXT NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE replenishment_tasks (id INTEGER PRIMARY KEY, shelf_id INTEGER)")
        connection.exec_driver_sql("CREATE TABLE inventory_snapshots (id INTEGER PRIMARY KEY, location_code TEXT)")
        connection.exec_driver_sql("""
            CREATE TABLE inventory_movements (
                id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, store_id INTEGER NOT NULL,
                source_snapshot_id INTEGER NOT NULL
            )
        """)
        connection.exec_driver_sql("""
            CREATE TRIGGER trg_inventory_movements_no_update
            BEFORE UPDATE ON inventory_movements
            BEGIN SELECT RAISE(ABORT, 'inventory_movements is append-only'); END
        """)
        connection.exec_driver_sql("""
            CREATE TRIGGER trg_inventory_movements_no_delete
            BEFORE DELETE ON inventory_movements
            BEGIN SELECT RAISE(ABORT, 'inventory_movements is append-only'); END
        """)
        connection.exec_driver_sql("INSERT INTO zones (id, store_id) VALUES (1, 10)")
        connection.exec_driver_sql("INSERT INTO shelves (id, zone_id, code) VALUES (20, 1, 'A-01')")
        connection.exec_driver_sql("INSERT INTO replenishment_tasks (id, shelf_id) VALUES (30, 20), (31, NULL)")
        connection.exec_driver_sql("INSERT INTO inventory_snapshots (id, location_code) VALUES (40, 'BACKROOM-A'), (41, NULL)")
        connection.exec_driver_sql("""
            INSERT INTO inventory_movements (id, task_id, store_id, source_snapshot_id)
            VALUES (1, 30, 10, 40), (2, 31, 10, 41)
        """)

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        rows = connection.exec_driver_sql("""
            SELECT operation_id, source_location_code, destination_shelf_id
            FROM inventory_movements ORDER BY id
        """).all()
        assert len(rows) == 2
        assert UUID(rows[0][0])
        assert UUID(rows[1][0])
        assert rows[0][0] != rows[1][0]
        assert rows[0][1:] == ("BACKROOM-A", 20)
        assert rows[1][1:] == (None, None)

        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql(
                "UPDATE inventory_movements SET source_location_code = 'CHANGED' WHERE id = 1"
            )

        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql("DELETE FROM inventory_movements WHERE id = 1")

        with pytest.raises(IntegrityError, match="require operation identity"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_movements
                    (id, task_id, store_id, source_snapshot_id, operation_id,
                     source_location_code, destination_shelf_id)
                VALUES (3, 30, 10, 40, NULL, 'BACKROOM-A', 20)
            """)

        with pytest.raises(IntegrityError, match="require operation identity"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_movements
                    (id, task_id, store_id, source_snapshot_id, operation_id,
                     source_location_code, destination_shelf_id)
                VALUES (4, 30, 10, 40, '12345678123456781234567812345678',
                        'BACKROOM-A', 999)
            """)

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

    engine.dispose()
