"""SQLite contract tests for the fenced output-publication migration."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_output_publication_migration_guards_fencing_scope_and_append_only(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0063_dataset_job_output_publications.py"
    spec = importlib.util.spec_from_file_location("dataset_output_publication_0063", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'output-publications.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql(
            "CREATE TABLE dataset_execution_jobs (id INTEGER PRIMARY KEY, status TEXT, fencing_token INTEGER, "
            "output_sha256 TEXT, staged_output_reference TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE dataset_execution_job_events (id INTEGER PRIMARY KEY, job_id INTEGER, "
            "sequence_number INTEGER, event_type TEXT, fencing_token INTEGER, worker_id TEXT, details TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE dataset_workers (worker_id TEXT PRIMARY KEY, status TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE dataset_worker_credentials (credential_id TEXT PRIMARY KEY, worker_id TEXT, "
            "revoked_at TEXT, expires_at TEXT, scopes TEXT)"
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        digest = "a" * 64
        staged = "staging/1/model.bin"
        connection.exec_driver_sql(
            "INSERT INTO dataset_execution_jobs VALUES (1,'SUCCEEDED',3,?,?)", (digest, staged)
        )
        connection.exec_driver_sql(
            "INSERT INTO dataset_execution_job_events VALUES "
            "(1,1,4,'SUCCEEDED',3,'worker-a',?)",
            ('{"output_sha256":"' + digest + '"}',),
        )
        connection.exec_driver_sql("INSERT INTO dataset_workers VALUES ('worker-a','ACTIVE')")
        connection.exec_driver_sql(
            "INSERT INTO dataset_worker_credentials VALUES "
            "('credential-a','worker-a',NULL,'2099-01-01T00:00:00+00:00','[\"outputs:publish\"]')"
        )
        valid = (
            "INSERT INTO dataset_execution_job_output_publications "
            "(job_id,worker_id,credential_id,fencing_token,output_sha256,staged_output_reference,"
            "published_output_reference,bytes_published,created_at) "
            "VALUES (1,'worker-a','credential-a',3,? ,?,'published/1/3-output.artifact',20,"
            "'2026-11-19T00:00:00+00:00')"
        )
        connection.exec_driver_sql(valid, (digest, staged))
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO dataset_execution_job_output_publications "
                "(job_id,worker_id,credential_id,fencing_token,output_sha256,staged_output_reference,"
                "published_output_reference,bytes_published,created_at) "
                "VALUES (1,'worker-a','credential-a',2,? ,?,'published/1/2-output.artifact',20,"
                "'2026-11-19T00:00:00+00:00')", (digest, staged)
            )
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql(
                "UPDATE dataset_execution_job_output_publications SET bytes_published=1 WHERE job_id=1"
            )
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql(
                "DELETE FROM dataset_execution_job_output_publications WHERE job_id=1"
            )
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
    engine.dispose()
