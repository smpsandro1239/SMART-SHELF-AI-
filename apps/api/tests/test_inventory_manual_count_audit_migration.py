"""SQLite migration contract for the manual inventory count audit ledger."""

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
        / "0091_inventory_manual_count_audit.py"
    )
    spec = importlib.util.spec_from_file_location(
        "inventory_manual_count_audit_migration", path
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def _insert_event(connection, *, snapshot_id=1, store_id=10, product_id=30, actor_id=20):
    connection.exec_driver_sql(
        """
        INSERT INTO inventory_manual_count_events
            (snapshot_id, store_id, product_id, actor_user_id, reason, created_at)
        VALUES (?, ?, ?, ?, 'Contagem física validada', CURRENT_TIMESTAMP)
        """,
        (snapshot_id, store_id, product_id, actor_id),
    )


def test_manual_count_audit_migration_enforces_provenance_and_append_only(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'manual-count-audit.db'}")

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE products (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                store_id INTEGER REFERENCES stores(id),
                role VARCHAR(30) NOT NULL,
                is_active BOOLEAN NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE inventory_snapshots (
                id INTEGER PRIMARY KEY,
                store_id INTEGER NOT NULL REFERENCES stores(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                source VARCHAR(30) NOT NULL,
                UNIQUE (id, store_id, product_id)
            )
            """
        )
        connection.exec_driver_sql("INSERT INTO stores (id) VALUES (10), (11)")
        connection.exec_driver_sql("INSERT INTO products (id) VALUES (30)")
        connection.exec_driver_sql(
            """
            INSERT INTO users (id, store_id, role, is_active) VALUES
                (20, 10, 'SUPERVISOR', 1),
                (21, 11, 'SUPERVISOR', 1),
                (22, 10, 'SUPERVISOR', 0),
                (23, 10, 'EMPLOYEE', 1),
                (24, NULL, 'ADMIN', 1)
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO inventory_snapshots (id, store_id, product_id, source) "
            "VALUES (1, 10, 30, 'MANUAL'), (2, 10, 30, 'WMS'), "
            "(3, 10, 30, 'MANUAL')"
        )

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        # A valid same-store supervisor and a global administrator are accepted.
        _insert_event(connection)
        _insert_event(connection, snapshot_id=3, actor_id=24)

        # Provenance guards reject inactive, wrong-role and cross-store actors.
        for actor_id in (21, 22, 23):
            with pytest.raises(IntegrityError, match="provenance mismatch"):
                _insert_event(connection, actor_id=actor_id)

        # Only snapshots explicitly sourced from MANUAL can have this event.
        with pytest.raises(IntegrityError, match="provenance mismatch"):
            _insert_event(connection, snapshot_id=2)

        # The database-level append-only contract blocks both mutation paths.
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql(
                "UPDATE inventory_manual_count_events SET reason='alterado' WHERE id=1"
            )
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql(
                "DELETE FROM inventory_manual_count_events WHERE id=1"
            )

        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM inventory_manual_count_events"
        ).scalar_one() == 2

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM inventory_snapshots"
        ).scalar_one() == 3
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).all()
        }
        assert "inventory_manual_count_events" not in tables

    engine.dispose()
