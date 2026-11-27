"""SQLite migration coverage for Edge acknowledgement review immutability."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load(name):
    path=Path(__file__).parents[1]/"migrations"/"versions"/name
    spec=importlib.util.spec_from_file_location(name.replace(".py",""),path)
    module=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _apply(migration, connection, operation="upgrade"):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration,operation)()


def test_review_migration_enforces_identity_idempotency_and_append_only(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'edge-review.db'}")
    ack_migration=_load("0103_edge_task_acknowledgements.py")
    review_migration=_load("0104_edge_task_acknowledgement_reviews.py")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY)")
        db.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        db.exec_driver_sql("CREATE TABLE replenishment_tasks (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, UNIQUE(id, store_id))")
        db.exec_driver_sql("""CREATE TABLE edge_device_task_assignments (
            id INTEGER PRIMARY KEY, device_id VARCHAR(120) NOT NULL, task_id INTEGER NOT NULL,
            store_id INTEGER NOT NULL, task_version INTEGER NOT NULL,
            UNIQUE(id, device_id, task_id, store_id, task_version))""")
        db.exec_driver_sql("""CREATE TABLE edge_device_event_inbox (
            id INTEGER PRIMARY KEY, device_id VARCHAR(120) NOT NULL, event_id VARCHAR(36) NOT NULL,
            UNIQUE(device_id,event_id))""")
        db.exec_driver_sql("INSERT INTO stores VALUES (1)")
        db.exec_driver_sql("INSERT INTO users VALUES (7)")
        db.exec_driver_sql("INSERT INTO replenishment_tasks VALUES (20,1)")
        db.exec_driver_sql("INSERT INTO edge_device_task_assignments VALUES (10,'review-device',20,1,3)")
        db.exec_driver_sql("INSERT INTO edge_device_event_inbox VALUES (30,'review-device','00000000-0000-4000-8000-000000000104')")
        _apply(ack_migration,db)
        db.exec_driver_sql("""INSERT INTO edge_task_acknowledgements
            (id,store_id,task_id,task_version,device_id,assignment_id,inbox_id,event_id,sequence_number,
             fingerprint_sha256,action,result,declared_at,received_at)
            VALUES (40,1,20,3,'review-device',10,30,'00000000-0000-4000-8000-000000000104',4,?,
                    'COMPLETED','REVIEW_REQUIRED','2026-11-27T06:00:00+00:00','2026-11-27T06:00:01+00:00')""",("c"*64,))
        _apply(review_migration,db)
        insert="""INSERT INTO edge_task_acknowledgement_reviews
            (id,store_id,task_id,acknowledgement_id,actor_user_id,decision,reason,evidence_reference,idempotency_key,reviewed_at)
            VALUES (1,1,20,40,7,'APPROVED','Verificação presencial','evidence://123','review-key-0001','2026-11-27T06:01:00+00:00')"""
        db.exec_driver_sql(insert)
        with pytest.raises(IntegrityError):
            db.exec_driver_sql(insert.replace("VALUES (1,1,20,40,7,'APPROVED'", "VALUES (2,1,20,40,7,'APPROVED'"))
        with pytest.raises(IntegrityError,match="append-only"):
            db.exec_driver_sql("UPDATE edge_task_acknowledgement_reviews SET decision='REJECTED' WHERE id=1")
        with pytest.raises(IntegrityError,match="append-only"):
            db.exec_driver_sql("DELETE FROM edge_task_acknowledgement_reviews WHERE id=1")
        _apply(review_migration,db,"downgrade")
    engine.dispose()
