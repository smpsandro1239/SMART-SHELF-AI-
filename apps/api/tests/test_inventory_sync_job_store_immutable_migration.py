"""SQLite migration contract: a sync job's tenant is immutable from creation, before its first audit event."""

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
        / "0101_inventory_sync_job_store_immutable.py"
    )
    spec = importlib.util.spec_from_file_location(
        "inventory_sync_job_store_immutable", path
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def test_inventory_sync_job_store_identity_is_immutable_but_worker_state_is_mutable(tmp_path):
    migration = _load_migration()
    engine = create_engine(
        f"sqlite:///{tmp_path / 'inventory-sync-job-store-immutable.db'}"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TABLE inventory_sync_jobs (
                id INTEGER PRIMARY KEY,
                store_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                fencing_token INTEGER NOT NULL DEFAULT 0
            )
        """)
        connection.exec_driver_sql("""
            INSERT INTO inventory_sync_jobs (id, store_id, status, fencing_token)
            VALUES (1, 10, 'QUEUED', 0)
        """)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        # Worker lifecycle fields remain mutable; same-value identity updates
        # are harmless and must not be rejected.
        connection.exec_driver_sql("""
            UPDATE inventory_sync_jobs
            SET status = 'RUNNING', fencing_token = 1, store_id = 10
            WHERE id = 1
        """)
        with pytest.raises(
            IntegrityError,
            match="inventory sync job store_id is immutable",
        ):
            connection.exec_driver_sql(
                "UPDATE inventory_sync_jobs SET store_id = 20 WHERE id = 1"
            )

        assert connection.exec_driver_sql(
            "SELECT store_id, status, fencing_token FROM inventory_sync_jobs WHERE id = 1"
        ).one() == (10, "RUNNING", 1)

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        # The downgrade removes only the guard.
        connection.exec_driver_sql(
            "UPDATE inventory_sync_jobs SET store_id = 20 WHERE id = 1"
        )
        assert connection.exec_driver_sql(
            "SELECT store_id FROM inventory_sync_jobs WHERE id = 1"
        ).scalar_one() == 20
    engine.dispose()
