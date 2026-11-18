from datetime import timedelta

import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.dataset_job_leases import (
    DatasetJobConflict, DatasetJobError, DatasetJobLeaseLost,
    claim_next_dataset_job, complete_dataset_job, enqueue_dataset_job,
    fail_dataset_job, heartbeat_dataset_job,
)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dataset-jobs.db'}")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    store = models.Store(code="DATASET-JOB-STORE", name="Dataset Job Store")
    session.add(store)
    session.flush()
    zone = models.Zone(store_id=store.id, name="Dataset Job Zone")
    session.add(zone)
    session.flush()
    shelf = models.Shelf(zone_id=zone.id, code="DATASET-JOB-SHELF")
    session.add(shelf)
    session.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id, original_filename="source.jpg", storage_path="/tmp/source.jpg",
        mime_type="image/jpeg", file_size_bytes=128, sha256="a" * 64,
        analysis_status="COMPLETED", retention_status="ACTIVE", legal_hold=False,
    )
    session.add(image)
    session.commit()
    session.info["source"] = {
        "shelf_image_id": image.id, "store_id": store.id,
        "source_image_sha256": image.sha256,
    }
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def approval():
    return {"status": "APPROVED", "mode": "training",
            "record_sha256": "b" * 64, "gate_report_sha256": "c" * 64}


def enqueue(db, key="dataset-job-1"):
    return enqueue_dataset_job(
        db, idempotency_key=key, release_fingerprint="d" * 64,
        approval_evidence=approval(), sources=[db.info["source"]],
    )


def test_enqueue_is_idempotent_and_audited(db):
    first, repeated = enqueue(db), enqueue(db)
    assert first.id == repeated.id and first.status == "QUEUED"
    events = db.query(models.DatasetExecutionJobEvent).filter_by(job_id=first.id).all()
    assert [(row.sequence_number, row.event_type) for row in events] == [(1, "QUEUED")]
    assert db.query(models.DatasetExecutionJobSource).filter_by(job_id=first.id).count() == 1


def test_idempotency_key_reuse_with_different_payload_conflicts(db):
    enqueue(db)
    with pytest.raises(DatasetJobConflict):
        enqueue_dataset_job(
            db, idempotency_key="dataset-job-1", release_fingerprint="e" * 64,
            approval_evidence=approval(), sources=[db.info["source"]],
        )


def test_claim_heartbeat_and_completion_use_current_fencing_token(db):
    job = enqueue(db)
    claim = claim_next_dataset_job(db, worker_id="worker-a", lease_seconds=30)
    assert claim.id == job.id and claim.status == "LEASED"
    assert claim.fencing_token == 1 and claim.attempt_count == 1
    heartbeat = heartbeat_dataset_job(
        db, job_id=job.id, worker_id="worker-a", fencing_token=1, lease_seconds=60
    )
    assert heartbeat.status == "LEASED" and heartbeat.fencing_token == 1
    completed = complete_dataset_job(
        db, job_id=job.id, worker_id="worker-a", fencing_token=1,
        output_sha256="f" * 64, staged_output_reference="staging/job-1/attempt-1/output.onnx",
    )
    assert completed.status == "SUCCEEDED" and completed.lease_owner is None
    assert [e.event_type for e in db.query(models.DatasetExecutionJobEvent).filter_by(job_id=job.id).order_by(
        models.DatasetExecutionJobEvent.sequence_number
    )] == ["QUEUED", "CLAIMED", "HEARTBEAT", "SUCCEEDED"]


def test_takeover_increments_token_and_rejects_stale_worker(db):
    job = enqueue(db)
    old = claim_next_dataset_job(db, worker_id="worker-old", lease_seconds=30)
    db.execute(update(models.DatasetExecutionJob).where(
        models.DatasetExecutionJob.id == job.id
    ).values(lease_expires_at=models.utc_now() - timedelta(seconds=1)))
    db.commit()
    new = claim_next_dataset_job(db, worker_id="worker-new", lease_seconds=30)
    assert new.fencing_token == old.fencing_token + 1 and new.attempt_count == 2
    with pytest.raises(DatasetJobLeaseLost):
        heartbeat_dataset_job(db, job_id=job.id, worker_id="worker-old",
                              fencing_token=old.fencing_token, lease_seconds=30)
    with pytest.raises(DatasetJobLeaseLost):
        complete_dataset_job(db, job_id=job.id, worker_id="worker-old",
                             fencing_token=old.fencing_token, output_sha256="f" * 64,
                             staged_output_reference="staging/obsolete")
    done = complete_dataset_job(db, job_id=job.id, worker_id="worker-new",
                                fencing_token=new.fencing_token, output_sha256="e" * 64,
                                staged_output_reference="staging/current")
    assert done.status == "SUCCEEDED"


def test_source_restriction_revokes_job_before_claim(db):
    job = enqueue(db)
    image = db.get(models.ShelfImage, db.info["source"]["shelf_image_id"])
    image.retention_status = "RESTRICTED"
    db.commit()
    assert claim_next_dataset_job(db, worker_id="worker-a") is None
    db.refresh(job)
    assert job.status == "REVOKED" and job.failure_code == "SOURCE_INELIGIBLE"
    assert [e.event_type for e in db.query(models.DatasetExecutionJobEvent).filter_by(job_id=job.id).order_by(
        models.DatasetExecutionJobEvent.sequence_number
    )] == ["QUEUED", "REVOKED"]


def test_approval_and_internal_sources_are_mandatory(db):
    with pytest.raises(DatasetJobError, match="approval evidence"):
        enqueue_dataset_job(db, idempotency_key="bad", release_fingerprint="d" * 64,
                            approval_evidence={**approval(), "status": "BLOCKED"},
                            sources=[db.info["source"]])
    with pytest.raises(DatasetJobError, match="internal image source"):
        enqueue_dataset_job(db, idempotency_key="external", release_fingerprint="d" * 64,
                            approval_evidence=approval(), sources=[])


def test_expired_lease_cannot_be_renewed_without_takeover(db):
    job = enqueue(db)
    claim = claim_next_dataset_job(db, worker_id="worker-a", lease_seconds=30)
    db.execute(update(models.DatasetExecutionJob).where(
        models.DatasetExecutionJob.id == job.id
    ).values(lease_expires_at=models.utc_now() - timedelta(seconds=1)))
    db.commit()
    with pytest.raises(DatasetJobLeaseLost):
        heartbeat_dataset_job(db, job_id=job.id, worker_id="worker-a",
                              fencing_token=claim.fencing_token, lease_seconds=60)


def test_failed_job_is_terminal_and_failure_code_is_sanitised(db):
    job = enqueue(db)
    claim = claim_next_dataset_job(db, worker_id="worker-a")
    failed = fail_dataset_job(db, job_id=job.id, worker_id="worker-a",
                              fencing_token=claim.fencing_token, failure_code="PROVIDER_TIMEOUT")
    assert failed.status == "FAILED" and failed.failure_code == "PROVIDER_TIMEOUT"
    with pytest.raises(DatasetJobLeaseLost):
        heartbeat_dataset_job(db, job_id=job.id, worker_id="worker-a",
                              fencing_token=claim.fencing_token, lease_seconds=30)
