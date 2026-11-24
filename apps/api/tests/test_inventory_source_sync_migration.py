"""SQLite migration contract for immutable ERP/WMS synchronization history."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0077_inventory_source_sync_history.py"
    spec = importlib.util.spec_from_file_location("inventory_source_sync_history", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_source_sync_lifecycle_is_single_transition_and_events_are_append_only(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'source-sync.db'}")
    with engine.begin() as connection:
        for table in ("stores", "users"):
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.exec_driver_sql("""
            INSERT INTO inventory_source_syncs (
                id, store_id, source, provider, status, started_at, created_by_user_id, created_at
            ) VALUES (1, 1, 'ERP', 'ERP-test', 'STARTED', CURRENT_TIMESTAMP, 1, CURRENT_TIMESTAMP)
        """)
        connection.exec_driver_sql("""
            INSERT INTO inventory_source_sync_events (id, sync_id, event_type, actor_user_id, details, created_at)
            VALUES (1, 1, 'STARTED', 1, '{}', CURRENT_TIMESTAMP)
        """)
        connection.exec_driver_sql("""
            UPDATE inventory_source_syncs SET status = 'SUCCESS', finished_at = CURRENT_TIMESTAMP,
                received_records = 10, processed_records = 10 WHERE id = 1
        """)
        with pytest.raises(IntegrityError, match="inventory source sync lifecycle permits one STARTED-to-terminal transition only"):
            connection.exec_driver_sql("UPDATE inventory_source_syncs SET status = 'FAILED' WHERE id = 1")
        with pytest.raises(IntegrityError, match="inventory source sync events are append-only"):
            connection.exec_driver_sql("UPDATE inventory_source_sync_events SET event_type = 'COMPLETED' WHERE id = 1")
        with pytest.raises(IntegrityError, match="inventory source sync events are append-only"):
            connection.exec_driver_sql("DELETE FROM inventory_source_sync_events WHERE id = 1")
        with pytest.raises(IntegrityError, match="inventory source sync history cannot be deleted"):
            connection.exec_driver_sql("DELETE FROM inventory_source_syncs WHERE id = 1")
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
