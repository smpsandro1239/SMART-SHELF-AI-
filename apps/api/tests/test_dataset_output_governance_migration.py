"""SQLite contract tests for dataset-output governance migration 0065."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_output_governance_migration_enforces_sequence_state_and_append_only(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0065_dataset_output_governance_events.py"
    spec = importlib.util.spec_from_file_location("dataset_output_governance_0065", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'output-governance.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, is_active BOOLEAN NOT NULL)")
        db.exec_driver_sql("CREATE TABLE dataset_execution_job_output_publications (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        db.exec_driver_sql("INSERT INTO users VALUES (1,1)")
        db.exec_driver_sql("INSERT INTO users VALUES (2,0)")
        db.exec_driver_sql("INSERT INTO dataset_execution_job_output_publications VALUES (10)")
        db.exec_driver_sql("INSERT INTO dataset_execution_job_output_publications VALUES (11)")
        insert = """
            INSERT INTO dataset_execution_job_output_governance_events
            (publication_id,sequence_number,event_type,actor_user_id,reason,
             evidence_reference,evidence_sha256,details,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """
        now = "2026-11-19T00:00:00+00:00"
        db.exec_driver_sql(insert, (10,1,"RESTRICTION_APPLIED",1,"incident confirmed",None,None,"{}",now))
        with pytest.raises(IntegrityError, match="already active"):
            db.exec_driver_sql(insert, (10,2,"RESTRICTION_APPLIED",1,"duplicate",None,None,"{}",now))
        db.exec_driver_sql(insert, (10,2,"LEGAL_HOLD_APPLIED",1,"preserve evidence",None,None,"{}",now))
        with pytest.raises(IntegrityError, match="not active"):
            db.exec_driver_sql(insert, (10,3,"LEGAL_HOLD_RELEASED",1,"invalid release",None,None,"{}",now))
        db.exec_driver_sql(insert, (10,3,"RESTRICTION_RELEASED",1,"review completed",None,None,"{}",now))
        db.exec_driver_sql(insert, (10,4,"LEGAL_HOLD_RELEASED",1,"hold cleared",None,None,"{}",now))
        with pytest.raises(IntegrityError, match="consecutive"):
            db.exec_driver_sql(insert, (10,6,"RESTRICTION_APPLIED",1,"sequence gap",None,None,"{}",now))
        with pytest.raises(IntegrityError, match="active human actor"):
            db.exec_driver_sql(insert, (11,1,"RESTRICTION_APPLIED",2,"inactive actor",None,None,"{}",now))
        with pytest.raises(IntegrityError, match="append-only"):
            db.exec_driver_sql("UPDATE dataset_execution_job_output_governance_events SET reason='tampered' WHERE publication_id=10")
        with pytest.raises(IntegrityError, match="append-only"):
            db.exec_driver_sql("DELETE FROM dataset_execution_job_output_governance_events WHERE publication_id=10")
        assert db.exec_driver_sql("SELECT COUNT(*) FROM dataset_execution_job_output_governance_events WHERE publication_id=10").scalar_one() == 4
        with Operations.context(MigrationContext.configure(db)):
            migration.downgrade()
        assert "dataset_execution_job_output_governance_events" not in {
            row[0] for row in db.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    engine.dispose()
