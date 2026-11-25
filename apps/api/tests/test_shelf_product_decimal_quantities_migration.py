"""SQLite migration contract for decimal shelf quantities."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine


def _load_migration():
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0090_shelf_product_decimal_quantities.py"
    )
    spec = importlib.util.spec_from_file_location("shelf_product_decimal_quantities", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_shelf_quantities_migrate_to_decimal_and_downgrade_refuses_fractional_data(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'shelf-quantities.db'}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE shelf_products (
                id INTEGER PRIMARY KEY,
                target_quantity INTEGER NOT NULL,
                min_display_quantity INTEGER NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO shelf_products VALUES (1, 20, 2)"
        )

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        connection.exec_driver_sql(
            "UPDATE shelf_products SET target_quantity = 20.125, min_display_quantity = 0.375 WHERE id = 1"
        )
        values = connection.exec_driver_sql(
            "SELECT target_quantity, min_display_quantity FROM shelf_products WHERE id = 1"
        ).one()
        assert str(values.target_quantity) == "20.125"
        assert str(values.min_display_quantity) == "0.375"

        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(
                RuntimeError,
                match="fractional base-unit values exist",
            ):
                migration.downgrade()

        connection.exec_driver_sql(
            "UPDATE shelf_products SET target_quantity = 20, min_display_quantity = 2 WHERE id = 1"
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        columns = {
            row[1]: row[2]
            for row in connection.exec_driver_sql("PRAGMA table_info(shelf_products)").all()
        }
        assert columns["target_quantity"].upper() == "INTEGER"
        assert columns["min_display_quantity"].upper() == "INTEGER"

    engine.dispose()
