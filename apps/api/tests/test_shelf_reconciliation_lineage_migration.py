"""Database-level tests for migration 0099 shelf and reconciliation lineage."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0099_shelf_reconciliation_lineage.py"
    spec = importlib.util.spec_from_file_location("shelf_reconciliation_lineage", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _schema(connection):
    connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL)")
    connection.exec_driver_sql("CREATE TABLE products (id INTEGER PRIMARY KEY)")
    connection.exec_driver_sql("""
        CREATE TABLE shelf_products (
            id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL, product_id INTEGER NOT NULL
        )
    """)
    connection.exec_driver_sql("""
        CREATE TABLE observations (
            id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL, product_id INTEGER
        )
    """)
    connection.exec_driver_sql("""
        CREATE TABLE inventory_snapshots (
            id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, product_id INTEGER NOT NULL
        )
    """)
    connection.exec_driver_sql("""
        CREATE TABLE observation_alerts (
            id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL,
            shelf_id INTEGER NOT NULL, product_id INTEGER NOT NULL
        )
    """)
    connection.exec_driver_sql("""
        CREATE TABLE inventory_reconciliations (
            id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL,
            shelf_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
            observation_id INTEGER, backroom_snapshot_id INTEGER,
            erp_snapshot_id INTEGER, wms_snapshot_id INTEGER
        )
    """)
    connection.exec_driver_sql("INSERT INTO zones VALUES (1, 10), (2, 20)")
    connection.exec_driver_sql("INSERT INTO shelves VALUES (1, 1), (2, 2)")
    connection.exec_driver_sql("INSERT INTO products VALUES (100), (200)")
    connection.exec_driver_sql("INSERT INTO shelf_products VALUES (1, 1, 100), (2, 2, 200)")
    connection.exec_driver_sql("INSERT INTO observations VALUES (1, 1, 100), (2, 2, 200)")
    connection.exec_driver_sql("""
        INSERT INTO inventory_snapshots VALUES
            (1, 10, 100), (2, 10, 100), (3, 10, 100),
            (4, 20, 200), (5, 10, 200)
    """)


def test_sqlite_alert_and_reconciliation_lineage_is_enforced_atomically(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'lineage-0099.db'}")
    with engine.begin() as connection:
        _schema(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        connection.exec_driver_sql(
            "INSERT INTO observation_alerts VALUES (1, 10, 1, 100)"
        )
        connection.exec_driver_sql("""
            INSERT INTO inventory_reconciliations (
                id, store_id, shelf_id, product_id, observation_id,
                backroom_snapshot_id, erp_snapshot_id, wms_snapshot_id
            ) VALUES (1, 10, 1, 100, 1, 1, 2, 3)
        """)

        invalid_alerts = (
            (2, 20, 1, 100),  # valid shelf and SKU, wrong store
            (3, 10, 1, 200),  # valid product, not linked to this shelf
        )
        for row in invalid_alerts:
            with pytest.raises(IntegrityError, match="observation alert shelf/product/store lineage mismatch"):
                connection.exec_driver_sql(
                    "INSERT INTO observation_alerts VALUES (?, ?, ?, ?)", row
                )

        invalid_reconciliations = (
            # A real observation from another shelf/product.
            (2, 10, 1, 100, 2, None, None, None),
            # Each snapshot exists, but belongs to another store or SKU.
            (3, 10, 1, 100, None, 4, None, None),
            (4, 10, 1, 100, None, None, 5, None),
            (5, 10, 1, 100, None, None, None, 4),
        )
        for row in invalid_reconciliations:
            with pytest.raises(IntegrityError, match="inventory reconciliation evidence lineage mismatch"):
                connection.exec_driver_sql("""
                    INSERT INTO inventory_reconciliations (
                        id, store_id, shelf_id, product_id, observation_id,
                        backroom_snapshot_id, erp_snapshot_id, wms_snapshot_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, row)

        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM observation_alerts"
        ).scalar_one() == 1
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM inventory_reconciliations"
        ).scalar_one() == 1

        with pytest.raises(IntegrityError, match="shelf SKU association is referenced by retained evidence"):
            connection.exec_driver_sql(
                "DELETE FROM shelf_products WHERE shelf_id = 1 AND product_id = 100"
            )
        with pytest.raises(IntegrityError, match="observation is referenced by immutable reconciliation evidence"):
            connection.exec_driver_sql(
                "UPDATE observations SET product_id = 200 WHERE id = 1"
            )
        with pytest.raises(IntegrityError, match="cannot move shelf hierarchy across stores while evidence exists"):
            connection.exec_driver_sql("UPDATE zones SET store_id = 20 WHERE id = 1")

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()


def test_migration_refuses_inconsistent_historical_evidence_without_rewriting_it(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'lineage-0099-preflight.db'}")
    with engine.begin() as connection:
        _schema(connection)
        connection.exec_driver_sql(
            "INSERT INTO observation_alerts VALUES (1, 10, 1, 200)"
        )
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="1 invalid alerts"):
                migration.upgrade()
        assert connection.exec_driver_sql(
            "SELECT product_id FROM observation_alerts WHERE id = 1"
        ).scalar_one() == 200
    engine.dispose()
