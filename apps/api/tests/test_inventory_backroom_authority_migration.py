"""SQLite migration contract for WMS backroom authority and audit immutability."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load(name: str):
    path = Path(__file__).parents[1] / "migrations" / "versions" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_sqlite_wms_authority_migrations_preserve_snapshot_guards_and_audit_policy(tmp_path):
    migration_0084 = _load("0084_wms_backroom_location_authority.py")
    migration_0085 = _load("0085_inventory_backroom_policy_audit.py")
    engine = create_engine(f"sqlite:///{tmp_path / 'wms-authority.db'}")

    with engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TABLE inventory_snapshots (
                id INTEGER PRIMARY KEY,
                store_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                on_hand_quantity NUMERIC NOT NULL,
                reserved_quantity NUMERIC NOT NULL,
                source VARCHAR(20) NOT NULL,
                external_reference VARCHAR(120),
                captured_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL
            )
        """)
        connection.exec_driver_sql("""
            CREATE TABLE inventory_freshness_policies (
                id INTEGER PRIMARY KEY,
                store_id INTEGER NOT NULL,
                source VARCHAR(20) NOT NULL,
                max_age_minutes INTEGER NOT NULL
            )
        """)
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("""
            CREATE TRIGGER existing_snapshot_update_guard
            BEFORE UPDATE ON inventory_snapshots
            BEGIN SELECT RAISE(ABORT, 'inventory_snapshots is append-only'); END
        """)
        connection.exec_driver_sql("INSERT INTO users (id) VALUES (7)")

        with Operations.context(MigrationContext.configure(connection)):
            migration_0084.upgrade()
            migration_0085.upgrade()

        connection.exec_driver_sql("""
            INSERT INTO inventory_snapshots
                (id, store_id, product_id, on_hand_quantity, reserved_quantity,
                 source, external_reference, location_code, availability_status,
                 captured_at, created_at)
            VALUES
                (1, 1, 10, 20, 3, 'WMS', 'wms-row-1', 'BACKROOM-01',
                 'AVAILABLE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """)
        status = connection.exec_driver_sql(
            "SELECT availability_status FROM inventory_snapshots WHERE id = 1"
        ).scalar_one()
        assert status == "AVAILABLE"

        with pytest.raises(IntegrityError, match="location code cannot be blank"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_snapshots
                    (id, store_id, product_id, on_hand_quantity, reserved_quantity,
                     source, location_code, availability_status, captured_at, created_at)
                VALUES
                    (2, 1, 10, 10, 0, 'WMS', '   ', 'AVAILABLE',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """)

        with pytest.raises(IntegrityError, match="invalid inventory snapshot availability"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_snapshots
                    (id, store_id, product_id, on_hand_quantity, reserved_quantity,
                     source, location_code, availability_status, captured_at, created_at)
                VALUES
                    (3, 1, 10, 10, 0, 'WMS', 'BACKROOM-01', 'BROKEN',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """)

        with pytest.raises(IntegrityError, match="inventory_snapshots is append-only"):
            connection.exec_driver_sql(
                "UPDATE inventory_snapshots SET on_hand_quantity = 0 WHERE id = 1"
            )

        with pytest.raises(IntegrityError, match="only valid for WMS"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_freshness_policies
                    (id, store_id, source, max_age_minutes, backroom_location_code)
                VALUES (1, 1, 'ERP', 240, 'BACKROOM-01')
            """)

        connection.exec_driver_sql("""
            INSERT INTO inventory_freshness_policies
                (id, store_id, source, max_age_minutes, backroom_location_code)
            VALUES (2, 1, 'WMS', 240, 'BACKROOM-01')
        """)
        connection.exec_driver_sql("""
            INSERT INTO inventory_freshness_policy_events
                (id, policy_id, actor_user_id, previous_backroom_location_code,
                 new_backroom_location_code, reason, created_at)
            VALUES (1, 2, 7, NULL, 'BACKROOM-01',
                    'Location approved by store manager', CURRENT_TIMESTAMP)
        """)

        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql(
                "UPDATE inventory_freshness_policy_events SET reason = 'changed' WHERE id = 1"
            )
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql(
                "DELETE FROM inventory_freshness_policy_events WHERE id = 1"
            )

    engine.dispose()
