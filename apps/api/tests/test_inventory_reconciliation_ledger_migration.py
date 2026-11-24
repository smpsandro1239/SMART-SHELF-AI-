"""SQLite migration contract for immutable reconciliation evidence and append-only events."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0076_inventory_reconciliation_ledger.py"
    spec = importlib.util.spec_from_file_location("inventory_reconciliation_ledger", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_reconciliation_evidence_is_immutable_and_events_are_append_only(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'reconciliation-ledger.db'}")
    with engine.begin() as connection:
        for table in ("stores", "shelves", "products", "observations", "inventory_snapshots", "users"):
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.exec_driver_sql("""
            INSERT INTO inventory_reconciliations (
                id, store_id, shelf_id, product_id, display_target_quantity,
                comparison_status, evidence, review_status, created_by_user_id, created_at
            ) VALUES (1, 1, 1, 1, 10, 'DIVERGENCE', '{}', 'PENDING', 1, CURRENT_TIMESTAMP)
        """)
        connection.exec_driver_sql("""
            INSERT INTO inventory_reconciliation_events (
                id, reconciliation_id, event_type, actor_user_id, evidence, created_at
            ) VALUES (1, 1, 'CREATED', 1, '{}', CURRENT_TIMESTAMP)
        """)
        connection.exec_driver_sql("""
            UPDATE inventory_reconciliations SET review_status = 'APPROVED',
                reviewed_by_user_id = 2, reviewed_at = CURRENT_TIMESTAMP,
                review_reason = 'Contagem validada' WHERE id = 1
        """)
        with pytest.raises(IntegrityError, match="inventory reconciliation evidence is immutable"):
            connection.exec_driver_sql("UPDATE inventory_reconciliations SET evidence = '{\"changed\": true}' WHERE id = 1")
        with pytest.raises(IntegrityError, match="inventory_reconciliation_events is append-only"):
            connection.exec_driver_sql("UPDATE inventory_reconciliation_events SET reason = 'alterado' WHERE id = 1")
        with pytest.raises(IntegrityError, match="inventory_reconciliation_events is append-only"):
            connection.exec_driver_sql("DELETE FROM inventory_reconciliation_events WHERE id = 1")
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
