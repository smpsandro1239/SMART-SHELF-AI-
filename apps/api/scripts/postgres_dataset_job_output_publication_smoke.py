"""PostgreSQL smoke for atomic, fenced dataset output publication and audit guards."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from uuid import uuid4
import hashlib

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import models
from app.config import settings
from app.database import SessionLocal
from app.dataset_job_leases import claim_next_dataset_job, complete_dataset_job, enqueue_dataset_job
from app.dataset_job_output_publications import promote_dataset_job_output
from app.dataset_worker_credentials import authenticate_dataset_worker, issue_dataset_worker_credential


def _assert_rejected(db, statement, params, label):
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
    original_root = settings.dataset_output_storage_path
    with TemporaryDirectory(prefix="ss-dataset-output-publish-") as temporary:
        root = Path(temporary)
        settings.dataset_output_storage_path = str(root)
        payload = b"PostgreSQL fenced model output " + suffix.encode("ascii")
        digest = hashlib.sha256(payload).hexdigest()
        worker_id = f"pg-output-{suffix}"
        with SessionLocal() as db:
            store = models.Store(code=f"PG-OUTPUT-{suffix}", name="Output publication smoke")
            db.add(store)
            db.flush()
            zone = models.Zone(store_id=store.id, name="Output publication zone")
            db.add(zone)
            db.flush()
            shelf = models.Shelf(zone_id=zone.id, code=f"OUTPUT-{suffix}")
            db.add(shelf)
            db.flush()
            image = models.ShelfImage(
                shelf_id=shelf.id, original_filename="source.bin",
                storage_path="/not-read-by-publication-smoke/source.bin",
                mime_type="application/octet-stream", file_size_bytes=10,
                sha256=hashlib.sha256(b"0123456789").hexdigest(),
                analysis_status="COMPLETED", retention_status="ACTIVE", legal_hold=False,
            )
            db.add(image)
            db.commit()
            token, credential = issue_dataset_worker_credential(
                db, worker_id=worker_id,
                scopes=["jobs:claim", "jobs:complete", "outputs:publish"],
                expires_in_seconds=3600,
            )
            job = enqueue_dataset_job(
                db, idempotency_key=f"output-smoke-{suffix}", release_fingerprint="d" * 64,
                approval_evidence={
                    "status": "APPROVED", "mode": "training",
                    "record_sha256": "b" * 64, "gate_report_sha256": "c" * 64,
                },
                sources=[{
                    "shelf_image_id": image.id, "store_id": store.id,
                    "source_image_sha256": image.sha256,
                }],
            )
            claim = claim_next_dataset_job(db, worker_id=worker_id, lease_seconds=300)
            assert claim is not None and claim.id == job.id
            stage_dir = root / "staging" / str(job.id) / str(claim.fencing_token)
            stage_dir.mkdir(parents=True)
            (stage_dir / "model.bin").write_bytes(payload)
            complete_dataset_job(
                db, job_id=job.id, worker_id=worker_id, fencing_token=claim.fencing_token,
                output_sha256=digest, staged_output_reference=f"staging/{job.id}/{claim.fencing_token}/model.bin",
            )
            principal = authenticate_dataset_worker(db, bearer_token=token)
            job_id, token_value, credential_id = job.id, claim.fencing_token, credential.credential_id

        barrier = Barrier(2)
        def publish():
            with SessionLocal() as db:
                barrier.wait(timeout=10)
                row = promote_dataset_job_output(
                    db, principal=principal, job_id=job_id, fencing_token=token_value
                )
                return row.id

        with ThreadPoolExecutor(max_workers=2) as executor:
            publication_ids = list(executor.map(lambda _i: publish(), range(2)))
        assert publication_ids[0] == publication_ids[1]
        with SessionLocal() as db:
            row = db.query(models.DatasetExecutionJobOutputPublication).filter_by(job_id=job_id).one()
            assert row.bytes_published == len(payload) and row.output_sha256 == digest
            assert (root / row.published_output_reference).read_bytes() == payload
            _assert_rejected(
                db,
                "UPDATE dataset_execution_job_output_publications SET bytes_published=1 WHERE id=:id",
                {"id": row.id}, "publication audit UPDATE",
            )
            _assert_rejected(
                db,
                "DELETE FROM dataset_execution_job_output_publications WHERE id=:id",
                {"id": row.id}, "publication audit DELETE",
            )
            _assert_rejected(
                db,
                "INSERT INTO dataset_execution_job_output_publications "
                "(job_id,worker_id,credential_id,fencing_token,output_sha256,staged_output_reference,"
                "published_output_reference,bytes_published,created_at) "
                "VALUES (:job,:worker,:credential,:token,:digest,:staged,:published,1,now())",
                {
                    "job": job_id, "worker": worker_id, "credential": credential_id,
                    "token": token_value + 1, "digest": digest,
                    "staged": f"staging/{job_id}/{token_value}/model.bin",
                    "published": f"published/{job_id}/forged.artifact",
                },
                "stale fencing token publication",
            )
    settings.dataset_output_storage_path = original_root
    print(
        "PostgreSQL output publication smoke passed: concurrent promotion was idempotent, "
        "digest and fencing guards held, and publication audit remained append-only."
    )


if __name__ == "__main__":
    main()
