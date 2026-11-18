"""Prove dataset job lease claiming and fencing on PostgreSQL 16."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import sleep
from uuid import uuid4

from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import SessionLocal
from app.dataset_job_leases import (
    DatasetJobLeaseLost, claim_next_dataset_job, complete_dataset_job,
    enqueue_dataset_job, heartbeat_dataset_job,
)


def _fixture(suffix):
    with SessionLocal() as db:
        store = models.Store(code=f"PG-DATASET-JOB-{suffix}", name="Dataset lease smoke")
        db.add(store)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Dataset lease zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"PG-DATASET-{suffix}")
        db.add(shelf)
        db.flush()
        images = []
        for index, digest in enumerate(("a", "b"), start=1):
            image = models.ShelfImage(
                shelf_id=shelf.id, original_filename=f"source-{index}.jpg",
                storage_path=f"/tmp/dataset-job-{suffix}-{index}.jpg",
                mime_type="image/jpeg", file_size_bytes=10, sha256=digest * 64,
                analysis_status="COMPLETED", retention_status="ACTIVE", legal_hold=False,
            )
            db.add(image)
            images.append(image)
        db.commit()
        return [
            {"shelf_image_id": image.id, "store_id": store.id, "source_image_sha256": image.sha256}
            for image in images
        ]


def _enqueue(key, source):
    with SessionLocal() as db:
        return enqueue_dataset_job(
            db, idempotency_key=key, release_fingerprint="c" * 64,
            approval_evidence={
                "status": "APPROVED", "mode": "training",
                "record_sha256": "d" * 64, "gate_report_sha256": "e" * 64,
            },
            sources=[source],
        ).id


def _claim(worker, barrier):
    with SessionLocal() as db:
        barrier.wait(timeout=10)
        job = claim_next_dataset_job(db, worker_id=worker, lease_seconds=1)
        return None if job is None else (job.id, job.fencing_token, job.lease_owner)


def main():
    suffix = uuid4().hex[:10]
    source_one, source_two = _fixture(suffix)
    job_id = _enqueue(f"pg-dataset-{suffix}-one", source_one)

    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(
            lambda worker: _claim(worker, barrier), ["worker-one", "worker-two"]
        ))
    claimed = [item for item in results if item is not None]
    assert len(claimed) == 1, f"expected exactly one initial claimant: {results}"
    claimed_id, first_token, first_owner = claimed[0]
    assert claimed_id == job_id

    revoked_job_id = _enqueue(f"pg-dataset-{suffix}-two", source_two)
    with SessionLocal() as db:
        image = db.get(models.ShelfImage, source_two["shelf_image_id"])
        image.retention_status = "RESTRICTED"
        db.commit()

    sleep(1.1)

    with SessionLocal() as db:
        replacement = claim_next_dataset_job(db, worker_id="replacement-worker", lease_seconds=60)
        assert replacement is not None and replacement.id == job_id
        assert replacement.fencing_token == first_token + 1
        assert replacement.attempt_count == 2

    with SessionLocal() as db:
        for operation in (
            lambda: heartbeat_dataset_job(
                db, job_id=job_id, worker_id=first_owner,
                fencing_token=first_token, lease_seconds=60,
            ),
            lambda: complete_dataset_job(
                db, job_id=job_id, worker_id=first_owner,
                fencing_token=first_token, output_sha256="f" * 64,
                staged_output_reference=f"staging/{job_id}/obsolete",
            ),
        ):
            try:
                operation()
            except DatasetJobLeaseLost:
                pass
            else:
                raise AssertionError("obsolete worker was allowed to mutate the job")

    with SessionLocal() as db:
        try:
            db.execute(text("""
                UPDATE dataset_execution_jobs
                SET release_fingerprint = :digest
                WHERE id = :job_id
            """), {"job_id": job_id, "digest": "9" * 64})
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("database accepted mutation of an active job identity")

    with SessionLocal() as db:
        try:
            db.execute(text("""
                INSERT INTO dataset_execution_job_events
                    (job_id, sequence_number, event_type, fencing_token, details)
                VALUES (:job_id, 99, 'HEARTBEAT', :token, '{}'::json)
            """), {"job_id": job_id, "token": first_token + 1})
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("database accepted a non-contiguous event sequence")

        try:
            db.execute(text("""
                UPDATE dataset_execution_jobs
                SET lease_expires_at = lease_expires_at - INTERVAL '1 second'
                WHERE id = :job_id AND status = 'LEASED'
            """), {"job_id": job_id})
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("database accepted a heartbeat that shortens the lease")

    with SessionLocal() as db:
        completed = complete_dataset_job(
            db, job_id=job_id, worker_id="replacement-worker",
            fencing_token=first_token + 1, output_sha256="f" * 64,
            staged_output_reference=f"staging/{job_id}/{first_token + 1}/output",
        )
        assert completed.status == "SUCCEEDED"
        assert claim_next_dataset_job(db, worker_id="retention-check") is None
        revoked = db.get(models.DatasetExecutionJob, revoked_job_id)
        assert revoked.status == "REVOKED"
        assert revoked.failure_code == "SOURCE_INELIGIBLE"
        events = db.query(models.DatasetExecutionJobEvent).filter_by(job_id=job_id).order_by(
            models.DatasetExecutionJobEvent.sequence_number
        ).all()
        assert [e.event_type for e in events] == ["QUEUED", "CLAIMED", "CLAIMED", "SUCCEEDED"]
        assert [e.sequence_number for e in events] == [1, 2, 3, 4]

        for statement, parameters in (
            (
                """
                UPDATE dataset_execution_jobs
                SET status = 'LEASED', lease_owner = 'resurrected-worker',
                    lease_expires_at = now() + INTERVAL '60 seconds',
                    fencing_token = fencing_token + 1,
                    attempt_count = attempt_count + 1, finished_at = NULL
                WHERE id = :job_id
                """,
                {"job_id": job_id},
            ),
        ):
            try:
                db.execute(text(statement), parameters)
                db.commit()
            except IntegrityError:
                db.rollback()
            else:
                raise AssertionError("database accepted a terminal job mutation")

    print(
        "PostgreSQL dataset job lease smoke passed: concurrent single claim, "
        "expired-lease takeover, monotonic fencing, stale-worker rejection, "
        "source-retention revocation and append-only event sequence."
    )


if __name__ == "__main__":
    main()
