"""Backfill migration for unique internal-product external mappings."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0082_inventory_external_mapping_product_unique.py"
    spec = importlib.util.spec_from_file_location("inventory_mapping_product_unique", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_legacy_schema(connection):
    connection.exec_driver_sql("""
        CREATE TABLE inventory_external_product_mappings (
            id INTEGER PRIMARY KEY,
            store_id INTEGER NOT NULL,
            source VARCHAR(8) NOT NULL,
            product_id INTEGER NOT NULL
        )
    """)


def test_backfill_adds_unique_index_to_existing_mapping_table():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _create_legacy_schema(connection)
        with Operations.context(MigrationContext.configure(connection)):
            _load_migration().upgrade()
        indexes = inspect(connection).get_indexes("inventory_external_product_mappings")
        assert any(item["name"] == "uq_inventory_external_mapping_product" for item in indexes)
        connection.exec_driver_sql(
            "INSERT INTO inventory_external_product_mappings (store_id, source, product_id) VALUES (1, 'ERP', 10)"
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO inventory_external_product_mappings (store_id, source, product_id) VALUES (1, 'ERP', 10)"
            )
    engine.dispose()


def test_backfill_refuses_to_hide_existing_duplicate_mappings():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _create_legacy_schema(connection)
        connection.exec_driver_sql("""
            INSERT INTO inventory_external_product_mappings (store_id, source, product_id)
            VALUES (1, 'ERP', 10), (1, 'ERP', 10)
        """)
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="duplicate store/source/product"):
                _load_migration().upgrade()
    engine.dispose()
