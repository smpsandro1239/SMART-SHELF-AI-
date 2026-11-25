"""SQLite migration and database-guard tests for the movement event ledger."""
import importlib.util
from pathlib import Path
from uuid import uuid4
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0087_inventory_movement_event_ledger.py"
    spec = importlib.util.spec_from_file_location("movement_event_ledger", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_movement_event_ledger_enforces_provenance_and_append_only(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'movement-events.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("""
            CREATE TABLE inventory_movements (
                id INTEGER PRIMARY KEY, operation_id CHAR(32) NOT NULL,
                store_id INTEGER NOT NULL, actor_user_id INTEGER NOT NULL, reason TEXT NOT NULL
            )
        """)
        connection.exec_driver_sql("INSERT INTO stores (id) VALUES (10)")
        connection.exec_driver_sql("INSERT INTO users (id) VALUES (20), (21)")
        operation_id = uuid4().hex
        connection.exec_driver_sql(
            "INSERT INTO inventory_movements (id, operation_id, store_id, actor_user_id, reason) VALUES (1, ?, 10, 20, 'Reposição confirmada')",
            (operation_id,),
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.exec_driver_sql("""
            INSERT INTO inventory_movement_events
                (movement_id, operation_id, store_id, event_type, actor_user_id, reason, evidence, created_at)
            VALUES (1, ?, 10, 'MOVEMENT_RECORDED', 20, 'Reposição confirmada', '{}', CURRENT_TIMESTAMP)
        """, (operation_id,))
        # Later external/system events share movement identity but have their own actor and reason.
        connection.exec_driver_sql("""
            INSERT INTO inventory_movement_events
                (movement_id, operation_id, store_id, event_type, actor_user_id, reason, evidence, created_at)
            VALUES (1, ?, 10, 'WMS_CONFIRMATION_RECORDED', 21, 'Confirmação externa recebida', '{}', CURRENT_TIMESTAMP)
        """, (operation_id,))
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql("UPDATE inventory_movement_events SET reason = 'alterado' WHERE movement_id = 1")
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql("DELETE FROM inventory_movement_events WHERE movement_id = 1")
        with pytest.raises(IntegrityError, match="provenance mismatch"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_movement_events
                    (movement_id, operation_id, store_id, event_type, actor_user_id, reason, evidence, created_at)
                VALUES (1, ?, 10, 'MOVEMENT_RECORDED', 21, 'Actor incorrecto para o evento inicial', '{}', CURRENT_TIMESTAMP)
            """, (operation_id,))
        with pytest.raises(IntegrityError, match="provenance mismatch"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_movement_events
                    (movement_id, operation_id, store_id, event_type, actor_user_id, reason, evidence, created_at)
                VALUES (1, ?, 10, 'COMPENSATION_RECORDED', 21, 'Operação diferente', '{}', CURRENT_TIMESTAMP)
            """, (uuid4().hex,))
        with pytest.raises(IntegrityError, match="CHECK constraint failed"):
            connection.exec_driver_sql("""
                INSERT INTO inventory_movement_events
                    (movement_id, operation_id, store_id, event_type, actor_user_id, reason, evidence, created_at)
                VALUES (1, ?, 10, 'UNSUPPORTED', 20, 'Reposição confirmada', '{}', CURRENT_TIMESTAMP)
            """, (operation_id,))
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
