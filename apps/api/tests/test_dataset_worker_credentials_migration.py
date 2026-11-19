"""SQLite migration contract for worker credential immutability and audit guards."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_worker_credentials_and_events_are_database_guarded(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0060_dataset_worker_credentials.py"
    spec = importlib.util.spec_from_file_location("dataset_worker_credentials_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine(f"sqlite:///{tmp_path / 'dataset-worker-guards.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        connection.exec_driver_sql(
            "INSERT INTO dataset_workers (worker_id,status,created_at) "
            "VALUES ('worker-one','ACTIVE','2026-11-19T00:00:00+00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO dataset_worker_credentials "
            "(id,credential_id,worker_id,secret_sha256,scopes,created_at,expires_at) "
            "VALUES (1,'" + "a" * 32 + "','worker-one','" + "b" * 64
            + "','[\"jobs:claim\"]','2026-11-19T00:00:00+00:00','2026-12-19T00:00:00+00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO dataset_worker_credentials "
            "(id,credential_id,worker_id,secret_sha256,scopes,created_at,expires_at) "
            "VALUES (2,'" + "c" * 32 + "','worker-one','" + "d" * 64
            + "','[\"jobs:claim\"]','2026-11-19T00:00:00+00:00','2026-12-19T00:00:00+00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO dataset_worker_events "
            "(id,worker_id,event_type,details,created_at) "
            "VALUES (1,'worker-one','CREDENTIAL_ISSUED','{}','2026-11-19T00:00:00+00:00')"
        )

        with pytest.raises(IntegrityError, match="credential identity and grants"):
            connection.exec_driver_sql(
                "UPDATE dataset_worker_credentials SET scopes='[\"outputs:publish\"]' WHERE id=1"
            )
        with pytest.raises(IntegrityError, match="credential identity and grants"):
            connection.exec_driver_sql(
                "UPDATE dataset_worker_credentials SET secret_sha256='" + "e" * 64 + "' WHERE id=1"
            )
        with pytest.raises(IntegrityError, match="credential identity and grants"):
            connection.exec_driver_sql(
                "UPDATE dataset_worker_credentials SET expires_at='2027-01-01T00:00:00+00:00' WHERE id=1"
            )

        connection.exec_driver_sql(
            "UPDATE dataset_worker_credentials SET last_used_at='2026-11-19T00:00:01+00:00' WHERE id=1"
        )
        connection.exec_driver_sql(
            "UPDATE dataset_worker_credentials SET revoked_at='2026-11-19T00:00:02+00:00', "
            "replaced_by_credential_id='" + "c" * 32 + "' WHERE id=1"
        )
        with pytest.raises(IntegrityError, match="credential identity and grants"):
            connection.exec_driver_sql(
                "UPDATE dataset_worker_credentials SET revoked_at=NULL WHERE id=1"
            )
        with pytest.raises(IntegrityError, match="credential identity and grants"):
            connection.exec_driver_sql(
                "UPDATE dataset_worker_credentials SET last_used_at=NULL WHERE id=1"
            )

        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql(
                "UPDATE dataset_worker_events SET details='{\"changed\":true}' WHERE id=1"
            )
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql("DELETE FROM dataset_worker_events WHERE id=1")

        connection.exec_driver_sql(
            "UPDATE dataset_workers SET status='DISABLED', "
            "disabled_at='2026-11-19T00:00:03+00:00' WHERE worker_id='worker-one'"
        )
        with pytest.raises(IntegrityError, match="identity and disablement"):
            connection.exec_driver_sql(
                "UPDATE dataset_workers SET status='ACTIVE', disabled_at=NULL "
                "WHERE worker_id='worker-one'"
            )
        with pytest.raises(IntegrityError, match="identity and disablement"):
            connection.exec_driver_sql(
                "UPDATE dataset_workers SET worker_id='worker-two' WHERE worker_id='worker-one'"
            )

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
