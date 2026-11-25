"""Append-only migration contract for external product mapping audit events."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_external_mapping_audit_events_are_append_only(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0080_inventory_external_mapping_audit.py"
    spec = importlib.util.spec_from_file_location("inventory_external_mapping_audit", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'mapping-audit.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE inventory_external_product_mappings (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.exec_driver_sql("INSERT INTO inventory_external_product_mappings (id) VALUES (1)")
        connection.exec_driver_sql("INSERT INTO users (id) VALUES (1)")
        connection.exec_driver_sql("""INSERT INTO inventory_external_product_mapping_events
            (id, mapping_id, actor_user_id, event_type, before_state, after_state, reason, created_at)
            VALUES (1, 1, 1, 'CREATED', NULL, '{}', 'Initial mapping', CURRENT_TIMESTAMP)""")
        with pytest.raises(IntegrityError, match="inventory external product mapping events are append-only"):
            connection.exec_driver_sql("UPDATE inventory_external_product_mapping_events SET reason='changed' WHERE id=1")
        with pytest.raises(IntegrityError, match="inventory external product mapping events are append-only"):
            connection.exec_driver_sql("DELETE FROM inventory_external_product_mapping_events WHERE id=1")
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
