"""SQLite migration contract for inventory snapshot source-sync lineage."""
import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0092_inventory_snapshot_sync_lineage.py"
    spec = importlib.util.spec_from_file_location("inventory_snapshot_sync_lineage_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _insert_snapshot(connection, *, store_id, source, source_sync_id, reference):
    connection.exec_driver_sql(
        "INSERT INTO inventory_snapshots (store_id, product_id, source, source_sync_id, external_reference) VALUES (?, 30, ?, ?, ?)",
        (store_id, source, source_sync_id, reference),
    )


def test_snapshot_sync_lineage_requires_matching_active_run_and_preserves_legacy_rows(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'snapshot-sync-lineage.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE inventory_source_syncs (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), source VARCHAR(8) NOT NULL, status VARCHAR(12) NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE inventory_snapshots (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id), product_id INTEGER NOT NULL, source VARCHAR(20) NOT NULL, external_reference VARCHAR(120))")
        connection.exec_driver_sql("INSERT INTO stores (id) VALUES (10), (11)")
        connection.exec_driver_sql("""
            INSERT INTO inventory_source_syncs (id, store_id, source, status) VALUES
                (1, 10, 'WMS', 'STARTED'), (2, 11, 'WMS', 'STARTED'),
                (3, 10, 'ERP', 'STARTED'), (4, 10, 'WMS', 'SUCCESS')
        """)
        connection.exec_driver_sql("INSERT INTO inventory_snapshots (id, store_id, product_id, source, external_reference) VALUES (1, 10, 30, 'MANUAL', 'legacy-manual')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        _insert_snapshot(connection, store_id=10, source="WMS", source_sync_id=1, reference="valid-wms-run")
        _insert_snapshot(connection, store_id=10, source="ERP", source_sync_id=3, reference="valid-erp-run")
        for store_id, source, sync_id, reference in (
            (11, "WMS", 1, "foreign-store-run"),
            (10, "ERP", 1, "wrong-source-run"),
            (10, "WMS", 4, "terminal-run"),
            (10, "WMS", 999, "missing-run"),
        ):
            with pytest.raises(IntegrityError, match="inventory snapshot source_sync_id provenance mismatch"):
                _insert_snapshot(connection, store_id=store_id, source=source, source_sync_id=sync_id, reference=reference)

        _insert_snapshot(connection, store_id=10, source="MANUAL", source_sync_id=None, reference="manual-no-sync")
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM inventory_snapshots").scalar_one() == 4
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM inventory_snapshots WHERE source_sync_id IS NULL").scalar_one() == 2
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM inventory_snapshots").scalar_one() == 4
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(inventory_snapshots)").all()}
        assert "source_sync_id" not in columns
    engine.dispose()
