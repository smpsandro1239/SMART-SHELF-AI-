"""SQLite coverage for preventing cascade deletion of shelf operational evidence."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


EVIDENCE_TABLES = (
    "observations",
    "observation_alerts",
    "shelf_products",
    "shelf_planograms",
    "inventory_reconciliations",
    "replenishment_tasks",
    "capture_sessions",
    "shelf_images",
    "edge_device_event_inbox",
)


def test_sqlite_shelf_and_zone_deletion_preserves_every_shelf_scoped_record(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0098_shelf_operational_evidence_retention.py"
    spec = importlib.util.spec_from_file_location("shelf_operational_evidence_retention", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'shelf-operational-evidence.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL)")
        for table in EVIDENCE_TABLES:
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL)")
        for index, table in enumerate(EVIDENCE_TABLES, start=1):
            connection.exec_driver_sql("INSERT INTO zones (id) VALUES (?)", (index,))
            connection.exec_driver_sql("INSERT INTO shelves (id, zone_id) VALUES (?, ?)", (index, index))
            connection.exec_driver_sql(f"INSERT INTO {table} (id, shelf_id) VALUES (?, ?)", (index, index))

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        for index, table in enumerate(EVIDENCE_TABLES, start=1):
            with pytest.raises(IntegrityError, match="shelf has retained operational evidence"):
                connection.exec_driver_sql("DELETE FROM shelves WHERE id = ?", (index,))
            with pytest.raises(IntegrityError, match="zone has retained shelf evidence"):
                connection.exec_driver_sql("DELETE FROM zones WHERE id = ?", (index,))
            connection.exec_driver_sql(f"DELETE FROM {table} WHERE id = ?", (index,))
            connection.exec_driver_sql("DELETE FROM shelves WHERE id = ?", (index,))
            connection.exec_driver_sql("DELETE FROM zones WHERE id = ?", (index,))

        assert connection.exec_driver_sql("SELECT COUNT(*) FROM shelves").scalar_one() == 0
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM zones").scalar_one() == 0
        for table in EVIDENCE_TABLES:
            assert connection.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one() == 0

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
