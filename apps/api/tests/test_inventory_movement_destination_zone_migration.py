"""Migration tests for immutable destination zone snapshots and backfill provenance."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_sqlite_movement_destination_zone_is_backfilled_and_captured_for_new_rows(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0095_inventory_movement_destination_zone.py"
    spec = importlib.util.spec_from_file_location("inventory_movement_destination_zone", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'movement-destination-zone.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, name VARCHAR(120) NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL, code VARCHAR(80) NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE replenishment_tasks (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, shelf_id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE inventory_movements (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, store_id INTEGER NOT NULL, destination_shelf_id INTEGER, destination_shelf_code VARCHAR(80) NOT NULL)")
        connection.exec_driver_sql("INSERT INTO zones (id, store_id, name) VALUES (1, 10, 'Corredor Norte')")
        connection.exec_driver_sql("INSERT INTO shelves (id, zone_id, code) VALUES (1, 1, 'N-01')")
        connection.exec_driver_sql("INSERT INTO replenishment_tasks (id, store_id, shelf_id) VALUES (1, 10, 1), (2, 10, 1)")
        connection.exec_driver_sql("INSERT INTO inventory_movements (id, task_id, store_id, destination_shelf_id, destination_shelf_code) VALUES (1, 1, 10, 1, 'N-01')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        old = connection.exec_driver_sql("SELECT destination_zone_id, destination_zone_name, destination_location_backfilled FROM inventory_movements WHERE id=1").one()
        assert old == (1, "Corredor Norte", 1)

        connection.exec_driver_sql("UPDATE zones SET name='Corredor Sul' WHERE id=1")
        connection.exec_driver_sql("UPDATE shelves SET code='S-02' WHERE id=1")
        connection.exec_driver_sql("""INSERT INTO inventory_movements
            (id, task_id, store_id, destination_shelf_id, destination_shelf_code, destination_zone_id, destination_zone_name)
            VALUES (2, 2, 10, 1, 'S-02', 1, 'Corredor Sul')""")
        new = connection.exec_driver_sql("SELECT destination_zone_name, destination_location_backfilled FROM inventory_movements WHERE id=2").one()
        assert new == ("Corredor Sul", 0)
        assert connection.exec_driver_sql("SELECT destination_zone_name FROM inventory_movements WHERE id=1").scalar_one() == "Corredor Norte"

        invalid = (
            (3, 2, 10, 1, "S-02", 1, "Corredor Norte", 0),
            (4, 2, 10, 1, "S-02", 99, "Corredor Sul", 0),
            (5, 2, 10, 1, "S-02", 1, "Corredor Sul", 1),
        )
        for values in invalid:
            with pytest.raises(IntegrityError, match="destination zone provenance mismatch"):
                connection.exec_driver_sql("""INSERT INTO inventory_movements
                    (id, task_id, store_id, destination_shelf_id, destination_shelf_code,
                     destination_zone_id, destination_zone_name, destination_location_backfilled)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", values)
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(inventory_movements)").all()}
        assert "destination_zone_id" not in columns
        assert "destination_zone_name" not in columns
        assert "destination_location_backfilled" not in columns
    engine.dispose()


def test_sqlite_destination_zone_migration_aborts_on_unverifiable_historical_lineage(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0095_inventory_movement_destination_zone.py"
    spec = importlib.util.spec_from_file_location("inventory_movement_destination_zone_invalid", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'movement-destination-zone-invalid.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, name VARCHAR(120) NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL, code VARCHAR(80) NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE replenishment_tasks (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, shelf_id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE inventory_movements (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, store_id INTEGER NOT NULL, destination_shelf_id INTEGER, destination_shelf_code VARCHAR(80) NOT NULL)")
        connection.exec_driver_sql("INSERT INTO zones (id, store_id, name) VALUES (1, 10, 'Corredor Norte')")
        connection.exec_driver_sql("INSERT INTO shelves (id, zone_id, code) VALUES (1, 1, 'N-01')")
        connection.exec_driver_sql("INSERT INTO replenishment_tasks (id, store_id, shelf_id) VALUES (1, 11, 1)")
        connection.exec_driver_sql("INSERT INTO inventory_movements (id, task_id, store_id, destination_shelf_id, destination_shelf_code) VALUES (1, 1, 10, 1, 'N-01')")
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="Cannot backfill 1 inventory movements"):
                migration.upgrade()
    engine.dispose()
