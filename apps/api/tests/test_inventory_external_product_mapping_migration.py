"""Migration contract for explicit store/source-scoped external SKU mappings."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
import pytest


def test_external_product_mapping_is_unique_per_store_and_source(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0078_inventory_external_product_mapping.py"
    spec = importlib.util.spec_from_file_location("inventory_external_product_mapping", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'external-mapping.db'}")
    with engine.begin() as connection:
        for table in ("stores", "users", "products"):
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.exec_driver_sql("INSERT INTO stores (id) VALUES (1), (2)")
        connection.exec_driver_sql("INSERT INTO users (id) VALUES (1)")
        connection.exec_driver_sql("INSERT INTO products (id) VALUES (1), (2)")
        base = """INSERT INTO inventory_external_product_mappings
            (store_id, source, external_product_id, external_sku, product_id,
             active, created_by_user_id, updated_by_user_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
        connection.exec_driver_sql(base, (1, "ERP", "ext-1", "SKU-1", 1))
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(base, (1, "ERP", "ext-1", "SKU-2", 2))
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(base, (1, "ERP", "ext-2", "SKU-1", 2))
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(base, (1, "ERP", "ext-2", "SKU-2", 1))
        connection.exec_driver_sql(base, (2, "ERP", "ext-1", "SKU-1", 2))
        connection.exec_driver_sql(base, (1, "WMS", "ext-1", "SKU-1", 2))
    engine.dispose()
