"""SQLite contract tests for output publication source-retention guards."""
import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_output_publication_rejects_restricted_or_held_sources(tmp_path):
    versions = Path(__file__).parents[1] / "migrations" / "versions"
    m63 = _load(versions / "0063_dataset_job_output_publications.py", "output_publication_0063")
    m64 = _load(versions / "0064_dataset_output_source_eligibility.py", "output_source_eligibility_0064")
    engine = create_engine(f"sqlite:///{tmp_path / 'output-source-eligibility.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("CREATE TABLE dataset_execution_jobs (id INTEGER PRIMARY KEY,status TEXT,fencing_token INTEGER,output_sha256 TEXT,staged_output_reference TEXT)")
        db.exec_driver_sql("CREATE TABLE dataset_execution_job_events (id INTEGER PRIMARY KEY,job_id INTEGER,sequence_number INTEGER,event_type TEXT,fencing_token INTEGER,worker_id TEXT,details TEXT)")
        db.exec_driver_sql("CREATE TABLE dataset_workers (worker_id TEXT PRIMARY KEY,status TEXT)")
        db.exec_driver_sql("CREATE TABLE dataset_worker_credentials (credential_id TEXT PRIMARY KEY,worker_id TEXT,revoked_at TEXT,expires_at TEXT,scopes TEXT)")
        db.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY,store_id INTEGER)")
        db.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY,zone_id INTEGER)")
        db.exec_driver_sql("CREATE TABLE shelf_images (id INTEGER PRIMARY KEY,shelf_id INTEGER,sha256 TEXT,retention_status TEXT,legal_hold INTEGER)")
        db.exec_driver_sql("CREATE TABLE dataset_execution_job_sources (id INTEGER PRIMARY KEY,job_id INTEGER,shelf_image_id INTEGER,store_id INTEGER,source_image_sha256 TEXT)")
        with Operations.context(MigrationContext.configure(db)):
            m63.upgrade()
            m64.upgrade()
        digest = "a" * 64
        db.exec_driver_sql("INSERT INTO zones VALUES (1,10)")
        db.exec_driver_sql("INSERT INTO shelves VALUES (1,1)")
        db.exec_driver_sql("INSERT INTO shelf_images VALUES (1,1,?,'ACTIVE',0)", (digest,))
        second_digest = "e" * 64
        db.exec_driver_sql("INSERT INTO shelf_images VALUES (2,1,?,'ACTIVE',0)", (second_digest,))
        db.exec_driver_sql("INSERT INTO dataset_workers VALUES ('worker-a','ACTIVE')")
        db.exec_driver_sql("INSERT INTO dataset_worker_credentials VALUES ('credential-a','worker-a',NULL,'2099-01-01T00:00:00+00:00','[\"outputs:publish\"]')")
        insert_job = "INSERT INTO dataset_execution_jobs VALUES (?, 'SUCCEEDED',3,?,?)"
        insert_event = "INSERT INTO dataset_execution_job_events VALUES (?, ?,4,'SUCCEEDED',3,'worker-a',?)"
        insert_source = "INSERT INTO dataset_execution_job_sources VALUES (?, ?,1,10,?)"
        insert_second_source = "INSERT INTO dataset_execution_job_sources VALUES (?, ?,2,10,?)"
        insert_pub = ("INSERT INTO dataset_execution_job_output_publications "
          "(job_id,worker_id,credential_id,fencing_token,output_sha256,staged_output_reference,published_output_reference,bytes_published,created_at) "
          "VALUES (?,?,?,?,?,?,?,?,?)")
        for job_id, status, hold, rejected in [(1,"ACTIVE",0,False),(2,"RESTRICTED",0,True),(3,"ACTIVE",1,True)]:
            db.exec_driver_sql(insert_job, (job_id,digest,f"staging/{job_id}/3/model.bin"))
            db.exec_driver_sql(insert_event, (job_id,job_id,'{"output_sha256":"' + digest + '"}'))
            db.exec_driver_sql(insert_source, (job_id,job_id,digest))
            db.exec_driver_sql("UPDATE shelf_images SET retention_status=?,legal_hold=? WHERE id=1",(status,hold))
            args=(job_id,"worker-a","credential-a",3,digest,f"staging/{job_id}/3/model.bin",f"published/{job_id}/3-output.artifact",20,"2026-11-19T00:00:00+00:00")
            if rejected:
                with pytest.raises(IntegrityError, match="source"):
                    db.exec_driver_sql(insert_pub,args)
            else:
                db.exec_driver_sql(insert_pub,args)

        # One ineligible member must block the complete multi-source publication,
        # even when another source is still ACTIVE and has a matching digest.
        db.exec_driver_sql("UPDATE shelf_images SET retention_status='ACTIVE',legal_hold=0 WHERE id=1")
        db.exec_driver_sql(insert_job, (4,digest,"staging/4/3/model.bin"))
        db.exec_driver_sql(insert_event, (4,4,'{"output_sha256":"' + digest + '"}'))
        db.exec_driver_sql(insert_source, (4,4,digest))
        db.exec_driver_sql(insert_second_source, (5,4,second_digest))
        db.exec_driver_sql("UPDATE shelf_images SET retention_status='RESTRICTED' WHERE id=2")
        multi_args=(4,"worker-a","credential-a",3,digest,"staging/4/3/model.bin","published/4/3-output.artifact",20,"2026-11-19T00:00:00+00:00")
        with pytest.raises(IntegrityError, match="source"):
            db.exec_driver_sql(insert_pub,multi_args)

        with Operations.context(MigrationContext.configure(db)):
            m64.downgrade()
            m63.downgrade()
    engine.dispose()
