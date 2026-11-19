"""PostgreSQL smoke for lease-fenced, retention-aware dataset source reads."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from tempfile import TemporaryDirectory
from uuid import uuid4
import hashlib

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import models
from app.config import settings
from app.database import SessionLocal
from app.dataset_job_artifact_reads import DatasetJobSourceIneligible, read_dataset_job_source_bytes
from app.dataset_job_leases import claim_next_dataset_job, enqueue_dataset_job
from app.dataset_worker_credentials import authenticate_dataset_worker, issue_dataset_worker_credential


def _assert_integrity_rejected(db, statement, params, label):
    try:
        db.execute(text(statement), params)
        db.commit()
    except IntegrityError:
        db.rollback()
        return
    db.rollback()
    raise AssertionError(f"{label} was accepted")


def main():
    suffix = uuid4().hex[:10]
    original_storage = settings.image_storage_path
    with TemporaryDirectory(prefix="ss-dataset-worker-read-") as temporary:
        root = Path(temporary)
        settings.image_storage_path = str(root)
        store_root = None
        payload = b"PostgreSQL approved dataset source " + suffix.encode("ascii")
        digest = hashlib.sha256(payload).hexdigest()

        with SessionLocal() as db:
            store = models.Store(code=f"PG-WORKER-READ-{suffix}", name="Worker read smoke")
            db.add(store)
            db.flush()
            store_root = root / str(store.id)
            store_root.mkdir(parents=True)
            path = store_root / "source.bin"
            path.write_bytes(payload)
            zone = models.Zone(store_id=store.id, name="Worker read zone")
            db.add(zone)
            db.flush()
            shelf = models.Shelf(zone_id=zone.id, code=f"WORKER-READ-{suffix}")
            db.add(shelf)
            db.flush()
            image = models.ShelfImage(
                shelf_id=shelf.id, original_filename="source.bin", storage_path=str(path),
                mime_type="application/octet-stream", file_size_bytes=len(payload),
                sha256=digest, analysis_status="COMPLETED",
                retention_status="ACTIVE", legal_hold=False,
            )
            db.add(image)
            db.commit()
            image_id, store_id = image.id, store.id

            token, credential = issue_dataset_worker_credential(
                db, worker_id=f"pg-reader-{suffix}",
                scopes=["jobs:claim", "artifacts:read"], expires_in_seconds=3600,
            )
            job = enqueue_dataset_job(
                db, idempotency_key=f"pg-read-job-{suffix}",
                release_fingerprint="d" * 64,
                approval_evidence={
                    "status": "APPROVED", "mode": "training",
                    "record_sha256": "b" * 64, "gate_report_sha256": "c" * 64,
                },
                sources=[{
                    "shelf_image_id": image_id, "store_id": store_id,
                    "source_image_sha256": digest,
                }],
            )
            claim = claim_next_dataset_job(db, worker_id=f"pg-reader-{suffix}", lease_seconds=300)
            assert claim is not None and claim.id == job.id
            principal = authenticate_dataset_worker(db, bearer_token=token)
            result = read_dataset_job_source_bytes(
                db, principal=principal, job_id=job.id,
                fencing_token=claim.fencing_token, shelf_image_id=image_id,
            )
            assert result == payload

        with SessionLocal() as db:
            audit = db.query(models.DatasetExecutionJobArtifactRead).filter_by(
                job_id=job.id
            ).one()
            audit_id = audit.id
            assert audit.bytes_read == len(payload) and audit.source_image_sha256 == digest
            _assert_integrity_rejected(
                db,
                "UPDATE dataset_execution_job_artifact_reads SET bytes_read = 1 WHERE id = :id",
                {"id": audit_id},
                "artifact read audit UPDATE",
            )
            _assert_integrity_rejected(
                db,
                "DELETE FROM dataset_execution_job_artifact_reads WHERE id = :id",
                {"id": audit_id},
                "artifact read audit DELETE",
            )

        blocker = SessionLocal()
        blocker.query(models.ShelfImage).filter_by(id=image_id).with_for_update().one()
        reader_started = Event()
        reader_finished = Event()
        application_name = f"ss-worker-read-{suffix}"

        def concurrent_read():
            with SessionLocal() as db:
                db.execute(text("SELECT set_config('application_name', :name, false)"), {"name": application_name})
                principal = authenticate_dataset_worker(db, bearer_token=token)
                db.commit()
                reader_started.set()
                try:
                    read_dataset_job_source_bytes(
                        db, principal=principal, job_id=job.id,
                        fencing_token=claim.fencing_token, shelf_image_id=image_id,
                    )
                    return "unexpectedly-allowed"
                except DatasetJobSourceIneligible:
                    return "denied-after-restriction"
                finally:
                    reader_finished.set()

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(concurrent_read)
                assert reader_started.wait(timeout=10), "worker read did not start"
                deadline = monotonic() + 10
                observed_wait = False
                while monotonic() < deadline:
                    with SessionLocal() as monitor:
                        activity = monitor.execute(text(
                            "SELECT wait_event_type, pg_blocking_pids(pid) "
                            "FROM pg_stat_activity WHERE application_name = :name"
                        ), {"name": application_name}).first()
                    if activity is not None and activity[0] == "Lock" and activity[1]:
                        observed_wait = True
                        break
                    if reader_finished.is_set():
                        break
                    sleep(0.05)
                assert observed_wait, "worker read did not wait on the source image lock"
                blocker.query(models.ShelfImage).filter_by(id=image_id).update(
                    {models.ShelfImage.retention_status: "RESTRICTED"},
                    synchronize_session=False,
                )
                blocker.commit()
                outcome = future.result(timeout=15)
                assert outcome == "denied-after-restriction", outcome
        finally:
            blocker.close()

        with SessionLocal() as db:
            count = db.query(models.DatasetExecutionJobArtifactRead).filter_by(
                job_id=job.id
            ).count()
            assert count == 1, f"restricted concurrent read created an audit row: {count}"

    settings.image_storage_path = original_storage
    print(
        "PostgreSQL dataset worker source-read smoke passed: bytes were read and audited "
        "under the current lease; a concurrent retention restriction blocked the next read."
    )


if __name__ == "__main__":
    main()
