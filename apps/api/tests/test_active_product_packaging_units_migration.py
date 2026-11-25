"""SQLite migration contract for active product packaging-unit uniqueness."""

import importlib.util
from pathlib import Path

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
        / "0054_unique_active_product_packaging_units.py"
    )
    spec = importlib.util.spec_from_file_location("unique_active_product_packaging_units", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _create_packaging_table(connection):
    connection.exec_driver_sql(
        """
        CREATE TABLE product_packaging_levels (
            id INTEGER PRIMARY KEY,
            product_id INTEGER NOT NULL,
            is_active BOOLEAN NOT NULL,
            is_ordering_unit BOOLEAN NOT NULL,
            is_replenishment_unit BOOLEAN NOT NULL
        )
        """
    )


def _run_upgrade(connection, migration):
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()


def _run_downgrade(connection, migration):
    with Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()


def test_migration_preflight_reports_existing_ordering_and_replenishment_duplicates(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'packaging-duplicates.db'}")

    with engine.begin() as connection:
        _create_packaging_table(connection)
        connection.exec_driver_sql(
            """
            INSERT INTO product_packaging_levels
                (id, product_id, is_active, is_ordering_unit, is_replenishment_unit)
            VALUES
                (1, 10, 1, 1, 0),
                (2, 10, 1, 1, 0),
                (3, 20, 1, 0, 1),
                (4, 20, 1, 0, 1),
                (5, 30, 0, 1, 1)
            """
        )

        with pytest.raises(RuntimeError) as error:
            _run_upgrade(connection, migration)

        message = str(error.value)
        assert "ordering: product_id=10 (2 active rows)" in message
        assert "replenishment: product_id=20 (2 active rows)" in message
        assert "No rows were modified" in message
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM product_packaging_levels"
        ).scalar_one() == 5
        indexes = connection.exec_driver_sql(
            "PRAGMA index_list('product_packaging_levels')"
        ).all()
        assert indexes == []

    engine.dispose()


def test_migration_enforces_active_unit_uniqueness_and_downgrade_removes_indexes(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'packaging-unique.db'}")

    with engine.begin() as connection:
        _create_packaging_table(connection)
        connection.exec_driver_sql(
            """
            INSERT INTO product_packaging_levels
                (id, product_id, is_active, is_ordering_unit, is_replenishment_unit)
            VALUES
                (1, 10, 1, 1, 0),
                (2, 10, 0, 1, 0),
                (3, 20, 1, 0, 1)
            """
        )
        _run_upgrade(connection, migration)

        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                """
                INSERT INTO product_packaging_levels
                    (id, product_id, is_active, is_ordering_unit, is_replenishment_unit)
                VALUES (4, 10, 1, 1, 0)
                """
            )

        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                """
                INSERT INTO product_packaging_levels
                    (id, product_id, is_active, is_ordering_unit, is_replenishment_unit)
                VALUES (5, 20, 1, 0, 1)
                """
            )

        _run_downgrade(connection, migration)
        connection.exec_driver_sql(
            """
            INSERT INTO product_packaging_levels
                (id, product_id, is_active, is_ordering_unit, is_replenishment_unit)
            VALUES (6, 10, 1, 1, 0)
            """
        )

    engine.dispose()
