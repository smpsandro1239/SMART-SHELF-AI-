"""SQLite contract for database-enforced dataset job fencing."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load(filename):
    path = Path(__file__).parents[1] / "migrations" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dataset_job_fencing_guards_and_event_sequence(tmp_path):
    base = _load("0056_dataset_execution_job_leases.py")
    guard = _load("0057_dataset_execution_fencing_guards.py")
    engine = create_engine(f"sqlite:///{tmp_path / 'dataset-job-fencing.db'}")
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
            base.upgrade()
            guard.upgrade()
        connection.exec_driver_sql(
            "INSERT INTO dataset_execution_jobs (id,idempotency_key,request_sha256,release_fingerprint,approval_record_sha256,approval_report_sha256,mode,status,fencing_token,attempt_count) VALUES "
            "(1,'key','" + "b" * 64 + "','" + "c" * 64 + "','" + "d" * 64 + "','" + "e" * 64 + "','training','QUEUED',0,0)"
        )
        connection.exec_driver_sql(
            "INSERT INTO dataset_execution_job_events (id,job_id,sequence_number,event_type,fencing_token,details) VALUES (1,1,1,'QUEUED',0,'{}')"
        )
        with pytest.raises(IntegrityError, match="sequence"):
            connection.exec_driver_sql(
                "INSERT INTO dataset_execution_job_events (id,job_id,sequence_number,event_type,fencing_token,details) VALUES (2,1,3,'CLAIMED',1,'{}')"
            )
        with pytest.raises(IntegrityError, match="fencing"):
            connection.exec_driver_sql(
                "UPDATE dataset_execution_jobs SET status='LEASED',lease_owner='worker-a',lease_expires_at=datetime('now','+1 minute'),fencing_token=2,attempt_count=1 WHERE id=1"
            )
        connection.exec_driver_sql(
            "UPDATE dataset_execution_jobs SET status='LEASED',lease_owner='worker-a',lease_expires_at=datetime('now','+1 minute'),fencing_token=1,attempt_count=1 WHERE id=1"
        )
        with pytest.raises(IntegrityError, match="fencing"):
            connection.exec_driver_sql(
                "UPDATE dataset_execution_jobs SET lease_owner='worker-b',lease_expires_at=datetime('now','+2 minutes'),fencing_token=2,attempt_count=2 WHERE id=1"
            )
        with pytest.raises(IntegrityError, match="successful dataset job"):
            connection.exec_driver_sql(
                "UPDATE dataset_execution_jobs SET status='SUCCEEDED',lease_owner=NULL,lease_expires_at=NULL,finished_at=CURRENT_TIMESTAMP WHERE id=1"
            )
        connection.exec_driver_sql(
            "UPDATE dataset_execution_jobs SET status='SUCCEEDED',lease_owner=NULL,lease_expires_at=NULL,output_sha256='" + "f" * 64 + "',staged_output_reference='staging/job/1/output',finished_at=CURRENT_TIMESTAMP WHERE id=1"
        )
        connection.exec_driver_sql(
            "INSERT INTO dataset_execution_job_events (id,job_id,sequence_number,event_type,fencing_token,details) VALUES (2,1,2,'SUCCEEDED',1,'{}')"
        )
        with pytest.raises(IntegrityError, match="terminal"):
            connection.exec_driver_sql(
                "INSERT INTO dataset_execution_job_events (id,job_id,sequence_number,event_type,fencing_token,details) VALUES (3,1,3,'SUCCEEDED',1,'{}')"
            )
        with Operations.context(MigrationContext.configure(connection)):
            guard.downgrade()
            base.downgrade()
    engine.dispose()
