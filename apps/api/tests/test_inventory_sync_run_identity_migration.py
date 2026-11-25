"""The provider run identity may be attached only during terminal completion."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load(name):
    path = Path(__file__).parents[1] / "migrations" / "versions" / name
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sync_run_identity_is_finalized_once_with_terminal_transition(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sync-run-identity.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            _load("0077_inventory_source_sync_history.py").upgrade()
            _load("0079_inventory_sync_run_identity.py").upgrade()
        connection.exec_driver_sql("INSERT INTO stores (id) VALUES (1)")
        connection.exec_driver_sql("INSERT INTO users (id) VALUES (1)")
        connection.exec_driver_sql("""INSERT INTO inventory_source_syncs
            (id, store_id, source, provider, status, started_at, created_by_user_id, created_at)
            VALUES (1, 1, 'ERP', 'vendor', 'STARTED', CURRENT_TIMESTAMP, 1, CURRENT_TIMESTAMP)""")
        connection.exec_driver_sql("""UPDATE inventory_source_syncs
            SET status='SUCCESS', external_run_id='vendor-run-1', finished_at=CURRENT_TIMESTAMP,
                received_records=0, processed_records=0 WHERE id=1""")
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql("""UPDATE inventory_source_syncs
                SET external_run_id='vendor-run-2' WHERE id=1""")
    engine.dispose()
