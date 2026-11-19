"""PostgreSQL smoke for atomic, fenced dataset output publication and audit guards."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from uuid import uuid4
import hashlib

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import models
from app.config import settings
from app.database import SessionLocal
from app.dataset_job_leases import claim_next_dataset_job, complete_dataset_job, enqueue_dataset_job
from app import dataset_job_output_publications as output_publications
from app.dataset_job_output_publications import (
    DatasetJobSourceIneligible,
    promote_dataset_job_output,
)
from app.dataset_worker_credentials import (
    DatasetWorkerAuthorizationError,
    authenticate_dataset_worker,
    issue_dataset_worker_credential,
    revoke_dataset_worker_credential,
)


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
            db.flush()
            second_image = models.ShelfImage(
                shelf_id=shelf.id, original_filename="second-source.bin",
                storage_path="/not-read-by-publication-smoke/second-source.bin",
                mime_type="application/octet-stream", file_size_bytes=11,
                sha256=hashlib.sha256(b"abcdefghijk").hexdigest(),
                analysis_status="COMPLETED", retention_status="ACTIVE", legal_hold=False,
            )
            db.add(second_image)
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
                sources=[
                    {
                        "shelf_image_id": second_image.id, "store_id": store.id,
                        "source_image_sha256": second_image.sha256,
                    },
                    {
                        "shelf_image_id": image.id, "store_id": store.id,
                        "source_image_sha256": image.sha256,
                    },
                ],
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
            source_image_id, source_store_id = image.id, store.id
            second_source_image_id, second_source_sha256 = second_image.id, second_image.sha256

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

        # A source may become restricted after completion but before promotion.
        held_payload = payload + b" source-retention-race"
        held_digest = hashlib.sha256(held_payload).hexdigest()
        with SessionLocal() as db:
            held_job = enqueue_dataset_job(
                db, idempotency_key=f"output-smoke-source-hold-{suffix}", release_fingerprint="f" * 64,
                approval_evidence={"status":"APPROVED","mode":"training","record_sha256":"b"*64,"gate_report_sha256":"c"*64},
                sources=[
                    {"shelf_image_id":second_source_image_id,"store_id":source_store_id,
                     "source_image_sha256":second_source_sha256},
                    {"shelf_image_id":source_image_id,"store_id":source_store_id,
                     "source_image_sha256":hashlib.sha256(b"0123456789").hexdigest()},
                ],
            )
            held_claim = claim_next_dataset_job(db, worker_id=worker_id, lease_seconds=300)
            assert held_claim is not None and held_claim.id == held_job.id
            held_stage = root / "staging" / str(held_job.id) / str(held_claim.fencing_token)
            held_stage.mkdir(parents=True)
            (held_stage / "model.bin").write_bytes(held_payload)
            complete_dataset_job(db, job_id=held_job.id, worker_id=worker_id, fencing_token=held_claim.fencing_token,
                output_sha256=held_digest, staged_output_reference=f"staging/{held_job.id}/{held_claim.fencing_token}/model.bin")
            held_job_id, held_token = held_job.id, held_claim.fencing_token

        source_prepared, source_resume = Event(), Event()
        original_prepare = output_publications._prepare_verified_bytes
        def pause_source_publication(**kwargs):
            result = original_prepare(**kwargs)
            source_prepared.set()
            if not source_resume.wait(timeout=20):
                raise TimeoutError("source-retention race was not released")
            return result
        def publish_after_source_hold():
            with SessionLocal() as db:
                try:
                    promote_dataset_job_output(db, principal=principal, job_id=held_job_id, fencing_token=held_token)
                except DatasetJobSourceIneligible:
                    return "rejected-after-source-hold"
                return "unexpectedly-published"
        def apply_source_hold():
            with SessionLocal() as db:
                image = db.query(models.ShelfImage).filter_by(id=second_source_image_id).with_for_update().one()
                image.legal_hold = True
                db.commit()
        output_publications._prepare_verified_bytes = pause_source_publication
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                publication_future = executor.submit(publish_after_source_hold)
                if not source_prepared.wait(timeout=10):
                    source_resume.set()
                    publication_future.result(timeout=20)
                    raise AssertionError("publication did not reach source preparation")
                executor.submit(apply_source_hold).result(timeout=5)
                source_resume.set()
                assert publication_future.result(timeout=20) == "rejected-after-source-hold"
        finally:
            source_resume.set()
            output_publications._prepare_verified_bytes = original_prepare
        with SessionLocal() as db:
            assert db.query(models.DatasetExecutionJobOutputPublication).filter_by(job_id=held_job_id).count() == 0
            assert (held_stage / "model.bin").read_bytes() == held_payload
            image = db.query(models.ShelfImage).filter_by(id=second_source_image_id).one()
            image.legal_hold = False
            db.commit()

        # Hold the promotion in its lock-free preparation phase while a second
        # PostgreSQL session revokes the credential. The revocation must commit
        # before preparation is released; final revalidation must then reject.
        revoked_payload = payload + b" revocation-race"
        revoked_digest = hashlib.sha256(revoked_payload).hexdigest()
        with SessionLocal() as db:
            revoked_job = enqueue_dataset_job(
                db, idempotency_key=f"output-smoke-revoke-{suffix}",
                release_fingerprint="e" * 64,
                approval_evidence={
                    "status": "APPROVED", "mode": "training",
                    "record_sha256": "b" * 64, "gate_report_sha256": "c" * 64,
                },
                sources=[{
                    "shelf_image_id": source_image_id, "store_id": source_store_id,
                    "source_image_sha256": hashlib.sha256(b"0123456789").hexdigest(),
                }],
            )
            revoked_claim = claim_next_dataset_job(db, worker_id=worker_id, lease_seconds=300)
            assert revoked_claim is not None and revoked_claim.id == revoked_job.id
            revoked_stage = root / "staging" / str(revoked_job.id) / str(revoked_claim.fencing_token)
            revoked_stage.mkdir(parents=True)
            (revoked_stage / "model.bin").write_bytes(revoked_payload)
            complete_dataset_job(
                db, job_id=revoked_job.id, worker_id=worker_id,
                fencing_token=revoked_claim.fencing_token, output_sha256=revoked_digest,
                staged_output_reference=(
                    f"staging/{revoked_job.id}/{revoked_claim.fencing_token}/model.bin"
                ),
            )
            revoked_job_id, revoked_token = revoked_job.id, revoked_claim.fencing_token

        prepared = Event()
        resume = Event()
        original_prepare = output_publications._prepare_verified_bytes

        def pause_after_prepare(**kwargs):
            prepared_result = original_prepare(**kwargs)
            prepared.set()
            if not resume.wait(timeout=20):
                raise TimeoutError("test did not release prepared output")
            return prepared_result

        def publish_revocation_race():
            with SessionLocal() as db:
                try:
                    promote_dataset_job_output(
                        db, principal=principal, job_id=revoked_job_id,
                        fencing_token=revoked_token,
                    )
                except DatasetWorkerAuthorizationError:
                    return "rejected-after-revocation"
                return "unexpectedly-published"

        def revoke_credential():
            with SessionLocal() as db:
                return revoke_dataset_worker_credential(db, credential_id=credential_id)

        output_publications._prepare_verified_bytes = pause_after_prepare
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                publication_future = executor.submit(publish_revocation_race)
                if not prepared.wait(timeout=10):
                    resume.set()
                    publication_future.result(timeout=20)
                    raise AssertionError("publication did not reach lock-free preparation")
                revocation_future = executor.submit(revoke_credential)
                try:
                    revoked = revocation_future.result(timeout=5)
                except TimeoutError:
                    resume.set()
                    try:
                        publication_future.result(timeout=20)
                    except Exception:
                        pass
                    raise AssertionError("credential revocation blocked during output preparation")
                assert revoked is True
                resume.set()
                assert publication_future.result(timeout=20) == "rejected-after-revocation"
        finally:
            resume.set()
            output_publications._prepare_verified_bytes = original_prepare

        with SessionLocal() as db:
            assert db.query(models.DatasetExecutionJobOutputPublication).filter_by(
                job_id=revoked_job_id
            ).count() == 0
            assert (revoked_stage / "model.bin").read_bytes() == revoked_payload
    settings.dataset_output_storage_path = original_root
    print(
        "PostgreSQL output publication smoke passed: concurrent promotion was idempotent, "
        "digest/fencing/audit guards held, and revocation committed during lock-free preparation."
    )


if __name__ == "__main__":
    main()
