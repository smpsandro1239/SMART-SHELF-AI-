import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dataset_job_artifact_read_database_guards_and_downgrade(tmp_path):
    migration_path = Path(__file__).parents[1] / "migrations" / "versions" / "0062_dataset_job_artifact_reads.py"
    migration = _load(migration_path)
    engine = create_engine(f"sqlite:///{tmp_path / 'job-artifact-read-guards.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE shelf_images (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL, sha256 TEXT NOT NULL, retention_status TEXT NOT NULL, legal_hold BOOLEAN NOT NULL, file_size_bytes INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE dataset_execution_jobs (id INTEGER PRIMARY KEY, status TEXT NOT NULL, lease_owner TEXT, fencing_token INTEGER NOT NULL, lease_expires_at TEXT)")
        connection.exec_driver_sql("CREATE TABLE dataset_execution_job_sources (job_id INTEGER NOT NULL, shelf_image_id INTEGER NOT NULL, store_id INTEGER NOT NULL, source_image_sha256 TEXT NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE dataset_workers (worker_id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE dataset_worker_credentials (credential_id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, scopes TEXT NOT NULL, revoked_at TEXT, expires_at TEXT NOT NULL)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.exec_driver_sql("INSERT INTO stores VALUES (1)")
        connection.exec_driver_sql("INSERT INTO zones VALUES (1, 1)")
        connection.exec_driver_sql("INSERT INTO shelves VALUES (1, 1)")
        connection.exec_driver_sql("INSERT INTO shelf_images VALUES (1, 1, '" + "a" * 64 + "', 'ACTIVE', 0, 12)")
        connection.exec_driver_sql("INSERT INTO dataset_execution_jobs VALUES (1, 'LEASED', 'worker-a', 1, datetime('now','+5 minutes'))")
        connection.exec_driver_sql("INSERT INTO dataset_execution_job_sources VALUES (1, 1, 1, '" + "a" * 64 + "')")
        connection.exec_driver_sql("INSERT INTO dataset_workers VALUES ('worker-a', 'ACTIVE')")
        connection.exec_driver_sql("INSERT INTO dataset_worker_credentials VALUES ('" + "b" * 32 + "', 'worker-a', '[\"artifacts:read\"]', NULL, datetime('now','+1 day'))")
        insert = (
            "INSERT INTO dataset_execution_job_artifact_reads "
            "(job_id,shelf_image_id,worker_id,credential_id,fencing_token,source_image_sha256,bytes_read,created_at) "
            "VALUES (1,1,'worker-a','" + "b" * 32 + "',1,'" + "a" * 64 + "',12,CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(insert)
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql("UPDATE dataset_execution_job_artifact_reads SET bytes_read=1 WHERE id=1")
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql("DELETE FROM dataset_execution_job_artifact_reads WHERE id=1")
        with pytest.raises(IntegrityError, match="active lease"):
            connection.exec_driver_sql(
                "INSERT INTO dataset_execution_job_artifact_reads "
                "(job_id,shelf_image_id,worker_id,credential_id,fencing_token,source_image_sha256,bytes_read,created_at) "
                "VALUES (1,1,'worker-b','" + "b" * 32 + "',1,'" + "a" * 64 + "',12,CURRENT_TIMESTAMP)"
            )
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
