"""Migration tests for immutable physical destination shelf snapshots."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_sqlite_movement_destination_shelf_code_is_backfilled_and_guarded(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0094_inventory_movement_destination_snapshot.py"
    spec = importlib.util.spec_from_file_location("inventory_movement_destination_snapshot", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'movement-destination.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL, code VARCHAR(80) NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE replenishment_tasks (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, shelf_id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE inventory_movements (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, store_id INTEGER NOT NULL, destination_shelf_id INTEGER)")
        connection.exec_driver_sql("INSERT INTO zones (id, store_id) VALUES (1, 10), (2, 20)")
        connection.exec_driver_sql("INSERT INTO shelves (id, zone_id, code) VALUES (1, 1, 'AISLE-01-SHELF-02'), (2, 2, 'FOREIGN-SHELF')")
        connection.exec_driver_sql("INSERT INTO replenishment_tasks (id, store_id, shelf_id) VALUES (1, 10, 1), (2, 10, 1)")
        connection.exec_driver_sql("INSERT INTO inventory_movements (id, task_id, store_id, destination_shelf_id) VALUES (1, 1, 10, NULL)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.exec_driver_sql("SELECT destination_shelf_id, destination_shelf_code FROM inventory_movements WHERE id=1").one() == (1, "AISLE-01-SHELF-02")
        connection.exec_driver_sql("INSERT INTO inventory_movements (id, task_id, store_id, destination_shelf_id, destination_shelf_code) VALUES (2, 2, 10, 1, 'AISLE-01-SHELF-02')")
        connection.exec_driver_sql("UPDATE shelves SET code='AISLE-01-SHELF-03' WHERE id=1")
        assert connection.exec_driver_sql("SELECT destination_shelf_code FROM inventory_movements WHERE id=1").scalar_one() == "AISLE-01-SHELF-02"
        connection.exec_driver_sql("INSERT INTO inventory_movements (id, task_id, store_id, destination_shelf_id, destination_shelf_code) VALUES (3, 2, 10, 1, 'AISLE-01-SHELF-03')")
        invalid = (
            (4, 2, 10, 1, None),
            (5, 2, 10, 1, "AISLE-01-SHELF-02"),
            (6, 2, 10, 2, "FOREIGN-SHELF"),
        )
        for values in invalid:
            with pytest.raises(IntegrityError, match="destination shelf provenance mismatch"):
                connection.exec_driver_sql("INSERT INTO inventory_movements (id, task_id, store_id, destination_shelf_id, destination_shelf_code) VALUES (?, ?, ?, ?, ?)", values)
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(inventory_movements)").all()}
        assert "destination_shelf_code" not in columns
    engine.dispose()
