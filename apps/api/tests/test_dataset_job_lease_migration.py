"""SQLite migration contract for dataset job immutability guards."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_dataset_job_migration_guards_sources_events_and_terminal_rows(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0056_dataset_execution_job_leases.py"
    spec = importlib.util.spec_from_file_location("dataset_job_lease_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'dataset-job-guards.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL)")
        connection.exec_driver_sql("CREATE TABLE shelf_images (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL, sha256 VARCHAR(64) NOT NULL, retention_status VARCHAR(20) NOT NULL, legal_hold BOOLEAN NOT NULL)")
        connection.exec_driver_sql("INSERT INTO stores VALUES (1)")
        connection.exec_driver_sql("INSERT INTO zones VALUES (1, 1)")
        connection.exec_driver_sql("INSERT INTO shelves VALUES (1, 1)")
        connection.exec_driver_sql("INSERT INTO shelf_images VALUES (1, 1, '" + "a" * 64 + "', 'ACTIVE', 0)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.exec_driver_sql(
            "INSERT INTO dataset_execution_jobs (id,idempotency_key,request_sha256,release_fingerprint,approval_record_sha256,approval_report_sha256,mode,status,fencing_token,attempt_count) VALUES "
            "(1,'key,'" + "b" * 64 + "','" + "c" * 64 + "','" + "d" * 64 + "','" + "e" * 64 + "','training','QUEUED',0,0)"
        )
        connection.exec_driver_sql(
            "INSERT INTO dataset_execution_job_sources (id,job_id,shelf_image_id,store_id,source_image_sha256) VALUES (1,1,1,1,'" + "a" * 64 + "')"
        )
        connection.exec_driver_sql(
            "INSERT INTO dataset_execution_job_events (id,job_id,sequence_number,event_type,fencing_token,details) VALUES (1,1,1,'QUEUED',0,'{}')"
        )
        with pytest.raises(IntegrityError, match="immutable"):
            connection.exec_driver_sql("UPDATE dataset_execution_job_sources SET store_id=2 WHERE id=1")
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql("UPDATE dataset_execution_job_events SET event_type='FAILED' WHERE id=1")
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql("DELETE FROM dataset_execution_job_events WHERE id=1")
        with pytest.raises(IntegrityError, match="immutable"):
            connection.exec_driver_sql("UPDATE dataset_execution_jobs SET release_fingerprint='" + "f" * 64 + "' WHERE id=1")
        connection.exec_driver_sql("UPDATE dataset_execution_jobs SET status='LEASED',lease_owner='worker',lease_expires_at=CURRENT_TIMESTAMP,fencing_token=1,attempt_count=1 WHERE id=1")
        connection.exec_driver_sql("UPDATE dataset_execution_jobs SET status='SUCCEEDED',lease_owner=NULL,lease_expires_at=NULL,output_sha256='" + "f" * 64 + "' WHERE id=1")
        with pytest.raises(IntegrityError, match="terminal"):
            connection.exec_driver_sql("UPDATE dataset_execution_jobs SET status='FAILED' WHERE id=1")
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
