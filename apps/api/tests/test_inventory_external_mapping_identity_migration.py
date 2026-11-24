"""Database-level guard for external mapping identity and deletion."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_external_mapping_identity_cannot_change_or_be_deleted(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0081_inventory_external_mapping_identity_guard.py"
    spec = importlib.util.spec_from_file_location("inventory_external_mapping_identity_guard", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'mapping-identity.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("""CREATE TABLE inventory_external_product_mappings (
            id INTEGER PRIMARY KEY, store_id INTEGER, source TEXT,
            external_product_id TEXT, external_sku TEXT, product_id INTEGER, active BOOLEAN)""")
        connection.exec_driver_sql("""INSERT INTO inventory_external_product_mappings
            VALUES (1, 10, 'ERP', 'external-1', 'SKU-1', 100, 1)""")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        with pytest.raises(IntegrityError, match="inventory external product mapping identity is immutable"):
            connection.exec_driver_sql("UPDATE inventory_external_product_mappings SET external_sku='SKU-2' WHERE id=1")
        connection.exec_driver_sql("UPDATE inventory_external_product_mappings SET product_id=101, active=0 WHERE id=1")
        with pytest.raises(IntegrityError, match="inventory external product mappings cannot be deleted"):
            connection.exec_driver_sql("DELETE FROM inventory_external_product_mappings WHERE id=1")
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
