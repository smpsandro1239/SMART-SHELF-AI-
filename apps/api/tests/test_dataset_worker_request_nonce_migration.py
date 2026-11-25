import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError


def _load_migration(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_request_nonce_migration_constraints_and_downgrade(tmp_path):
    migrations = Path(__file__).parents[1] / "migrations" / "versions"
    worker_migration = _load_migration(
        migrations / "0060_dataset_worker_credentials.py", "worker_0060"
    )
    nonce_migration = _load_migration(
        migrations / "0061_dataset_worker_request_nonces.py", "worker_nonce_0061"
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'worker-nonces.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        with Operations.context(MigrationContext.configure(connection)):
            worker_migration.upgrade()
            nonce_migration.upgrade()
        connection.exec_driver_sql(
            "INSERT INTO dataset_workers (worker_id,status,created_at) "
            "VALUES ('nonce-worker','ACTIVE','2026-11-19T00:00:00+00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO dataset_worker_credentials "
            "(id,credential_id,worker_id,secret_sha256,scopes,created_at,expires_at) "
            "VALUES (1,'0123456789abcdef0123456789abcdef','nonce-worker','"
            + "a" * 64
            + "','[\"jobs:claim\"]','2026-11-19T00:00:00+00:00','2026-12-19T00:00:00+00:00')"
        )
        insert = (
            "INSERT INTO dataset_worker_request_nonces "
            "(credential_id,nonce_sha256,request_timestamp,expires_at,created_at) "
            "VALUES ('0123456789abcdef0123456789abcdef','" + "b" * 64
            + "',1795046400,'2026-11-19T00:02:00+00:00','2026-11-19T00:00:00+00:00')"
        )
        connection.exec_driver_sql(insert)
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(insert)
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO dataset_worker_request_nonces "
                "(credential_id,nonce_sha256,request_timestamp,expires_at,created_at) "
                "VALUES ('0123456789abcdef0123456789abcdef','short',1795046400,"
                "'2026-11-19T00:02:00+00:00','2026-11-19T00:00:00+00:00')"
            )
        with Operations.context(MigrationContext.configure(connection)):
            nonce_migration.downgrade()
            worker_migration.downgrade()
        assert "dataset_worker_request_nonces" not in inspect(connection).get_table_names()
    engine.dispose()
