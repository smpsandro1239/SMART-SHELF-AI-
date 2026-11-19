from concurrent.futures import ThreadPoolExecutor
import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.config import settings
from app.database import Base
from app.dataset_job_leases import claim_next_dataset_job, complete_dataset_job, enqueue_dataset_job
from app.dataset_job_output_publications import (
    DatasetJobOutputIntegrityError,
    DatasetJobOutputUnavailable,
    promote_dataset_job_output,
)
from app.dataset_worker_credentials import (
    DatasetWorkerAuthorizationError,
    authenticate_dataset_worker,
    issue_dataset_worker_credential,
    revoke_dataset_worker_credential,
)


@pytest.fixture
def publication_setup(tmp_path, monkeypatch):
    root = tmp_path / "dataset-outputs"
    monkeypatch.setattr(settings, "dataset_output_storage_path", str(root))
    monkeypatch.setattr(settings, "max_dataset_output_bytes", 1024 * 1024)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    store = models.Store(code="OUTPUT-PUBLISH-STORE", name="Output publish store")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Output publish zone")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="OUTPUT-PUBLISH-SHELF")
    db.add(shelf)
    db.flush()
    payload = b"trained model output fixture"
    image = models.ShelfImage(
        shelf_id=shelf.id, original_filename="source.bin",
        storage_path="/not-read-by-this-test/source.bin",
        mime_type="application/octet-stream", file_size_bytes=10,
        sha256=hashlib.sha256(b"0123456789").hexdigest(),
        analysis_status="COMPLETED", retention_status="ACTIVE", legal_hold=False,
    )
    db.add(image)
    db.commit()
    worker_id = "output-publisher"
    token, credential = issue_dataset_worker_credential(
        db, worker_id=worker_id,
        scopes=["jobs:claim", "jobs:complete", "outputs:publish"],
        expires_in_seconds=3600,
    )
    job = enqueue_dataset_job(
        db, idempotency_key="output-publish-job", release_fingerprint="d" * 64,
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
    stage_path = stage_dir / "model.bin"
    stage_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    complete_dataset_job(
        db, job_id=job.id, worker_id=worker_id, fencing_token=claim.fencing_token,
        output_sha256=digest, staged_output_reference=f"staging/{job.id}/{claim.fencing_token}/model.bin",
    )
    principal = authenticate_dataset_worker(db, bearer_token=token)
    state = {
        "db": db, "factory": factory, "engine": engine, "root": root,
        "worker_id": worker_id, "token": token, "credential": credential,
        "job": job, "claim": claim, "principal": principal,
        "payload": payload, "digest": digest, "stage_path": stage_path,
    }
    yield state
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_promote_completed_output_and_record_immutable_publication(publication_setup):
    state = publication_setup
    publication = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    assert publication.output_sha256 == state["digest"]
    assert publication.worker_id == state["worker_id"]
    assert publication.bytes_published == len(state["payload"])
    assert publication.published_output_reference == (
        f"published/{state['job'].id}/{state['claim'].fencing_token}-{state['digest']}.artifact"
    )
    published_path = state["root"] / publication.published_output_reference
    assert published_path.read_bytes() == state["payload"]
    assert not state["stage_path"].exists()
    assert state["db"].query(models.DatasetExecutionJobOutputPublication).count() == 1


def test_publication_is_idempotent_after_success(publication_setup):
    state = publication_setup
    first = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    second = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    assert first.id == second.id
    assert state["db"].query(models.DatasetExecutionJobOutputPublication).count() == 1


def test_filesystem_promotion_is_reconciled_after_lost_database_commit(publication_setup):
    state = publication_setup
    publication_ref = (
        f"published/{state['job'].id}/{state['claim'].fencing_token}-{state['digest']}.artifact"
    )
    published = state["root"] / publication_ref
    published.parent.mkdir(parents=True)
    published.write_bytes(state["payload"])
    state["stage_path"].unlink()
    publication = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    assert publication.published_output_reference == publication_ref
    assert publication.bytes_published == len(state["payload"])


def test_tampered_staging_output_is_never_published(publication_setup):
    state = publication_setup
    state["stage_path"].write_bytes(b"tampered output")
    with pytest.raises(DatasetJobOutputIntegrityError):
        promote_dataset_job_output(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token,
        )
    assert state["db"].query(models.DatasetExecutionJobOutputPublication).count() == 0
    published_root = state["root"] / "published"
    assert not list(published_root.rglob("*.artifact"))


def test_missing_staged_output_without_recoverable_destination_is_rejected(publication_setup):
    state = publication_setup
    state["stage_path"].unlink()
    with pytest.raises(DatasetJobOutputUnavailable):
        promote_dataset_job_output(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token,
        )


def test_promotion_rechecks_persisted_scope_and_credential_revocation(publication_setup):
    state = publication_setup
    state["db"].commit()
    credential = state["db"].query(models.DatasetWorkerCredential).filter_by(
        credential_id=state["principal"].credential_id
    ).one()
    credential.scopes = ["jobs:claim", "jobs:complete"]
    state["db"].commit()
    with pytest.raises(DatasetWorkerAuthorizationError):
        promote_dataset_job_output(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token,
        )
    credential.scopes = ["jobs:claim", "jobs:complete", "outputs:publish"]
    state["db"].commit()
    with state["factory"]() as revoker:
        assert revoke_dataset_worker_credential(
            revoker, credential_id=state["principal"].credential_id
        )
    with pytest.raises(DatasetWorkerAuthorizationError):
        promote_dataset_job_output(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token,
        )
    assert state["db"].query(models.DatasetExecutionJobOutputPublication).count() == 0


def test_wrong_worker_or_fencing_token_cannot_promote(publication_setup):
    state = publication_setup
    from app.dataset_worker_credentials import DatasetWorkerPrincipal
    wrong_worker = DatasetWorkerPrincipal(
        worker_id="another-worker",
        credential_id=state["principal"].credential_id,
        scopes=frozenset({"outputs:publish"}),
    )
    from app.dataset_job_leases import DatasetJobLeaseLost
    with pytest.raises(DatasetJobLeaseLost):
        promote_dataset_job_output(
            state["db"], principal=wrong_worker, job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token,
        )
    with pytest.raises(DatasetJobLeaseLost):
        promote_dataset_job_output(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token + 1,
        )

def test_large_output_preparation_releases_db_transaction_and_rechecks_revocation(
    publication_setup, monkeypatch
):
    from app import dataset_job_output_publications as publications

    state = publication_setup
    original_prepare = publications._prepare_verified_bytes

    def prepare_then_revoke(**kwargs):
        # The file copy/hash phase must not retain even a read transaction.
        assert not state["db"].in_transaction()
        result = original_prepare(**kwargs)
        credential = state["db"].query(models.DatasetWorkerCredential).filter_by(
            credential_id=state["principal"].credential_id
        ).one()
        credential.revoked_at = models.utc_now()
        state["db"].commit()
        return result

    monkeypatch.setattr(publications, "_prepare_verified_bytes", prepare_then_revoke)
    with pytest.raises(DatasetWorkerAuthorizationError):
        promote_dataset_job_output(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token,
        )

    assert state["db"].query(models.DatasetExecutionJobOutputPublication).count() == 0
    assert state["stage_path"].exists()
    published_root = state["root"] / "published"
    assert not list(published_root.rglob("*.artifact"))
    assert not list(published_root.rglob("*.tmp"))

def test_output_reconciler_dry_run_then_removes_only_verified_old_files(publication_setup):
    import os
    from datetime import timedelta

    from app.dataset_job_output_reconciliation import reconcile_dataset_job_output_files

    state = publication_setup
    publication = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    state["stage_path"].parent.mkdir(parents=True, exist_ok=True)
    state["stage_path"].write_bytes(state["payload"])
    old_timestamp = (models.utc_now() - timedelta(days=8)).timestamp()
    os.utime(state["stage_path"], (old_timestamp, old_timestamp))

    temporary_dir = state["root"] / "published" / str(state["job"].id)
    temporary_dir.mkdir(parents=True, exist_ok=True)
    old_temp = temporary_dir / (".promotion-" + "a" * 32 + ".tmp")
    old_temp.write_bytes(b"abandoned temp")
    os.utime(old_temp, (old_timestamp, old_timestamp))
    recent_temp = temporary_dir / (".promotion-" + "b" * 32 + ".tmp")
    recent_temp.write_bytes(b"still recent")

    dry_run = reconcile_dataset_job_output_files(state["db"], grace_seconds=7 * 86400)
    assert dry_run["mode"] == "dry-run"
    assert dry_run["candidate_count"] == 2
    assert state["stage_path"].exists() and old_temp.exists() and recent_temp.exists()

    applied = reconcile_dataset_job_output_files(
        state["db"], apply=True, grace_seconds=7 * 86400
    )
    assert applied["removed_count"] == 2
    assert not state["stage_path"].exists()
    assert not old_temp.exists()
    assert recent_temp.exists()
    assert (state["root"] / publication.published_output_reference).read_bytes() == state["payload"]


def test_output_reconciler_preserves_staging_without_publication_or_with_wrong_digest(
    publication_setup
):
    import os
    from datetime import timedelta

    from app.dataset_job_output_reconciliation import reconcile_dataset_job_output_files

    state = publication_setup
    old_timestamp = (models.utc_now() - timedelta(days=8)).timestamp()
    os.utime(state["stage_path"], (old_timestamp, old_timestamp))
    no_publication = reconcile_dataset_job_output_files(
        state["db"], apply=True, grace_seconds=7 * 86400
    )
    assert no_publication["removed_count"] == 0
    assert state["stage_path"].exists()

    publication = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    state["stage_path"].parent.mkdir(parents=True, exist_ok=True)
    state["stage_path"].write_bytes(b"tampered staging bytes")
    os.utime(state["stage_path"], (old_timestamp, old_timestamp))
    mismatch = reconcile_dataset_job_output_files(
        state["db"], apply=True, grace_seconds=7 * 86400
    )
    assert mismatch["removed_count"] == 0
    assert state["stage_path"].exists()
    assert (state["root"] / publication.published_output_reference).read_bytes() == state["payload"]



def test_output_reconciler_preserves_staging_when_published_destination_is_corrupted(
    publication_setup,
):
    import os
    from datetime import timedelta

    from app.dataset_job_output_reconciliation import reconcile_dataset_job_output_files

    state = publication_setup
    publication = promote_dataset_job_output(
        state["db"],
        principal=state["principal"],
        job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )

    state["stage_path"].parent.mkdir(parents=True, exist_ok=True)
    state["stage_path"].write_bytes(state["payload"])
    old_timestamp = (models.utc_now() - timedelta(days=8)).timestamp()
    os.utime(state["stage_path"], (old_timestamp, old_timestamp))

    published_path = state["root"] / publication.published_output_reference
    published_path.write_bytes(b"corrupted published bytes")

    report = reconcile_dataset_job_output_files(
        state["db"], apply=True, grace_seconds=7 * 86400
    )

    assert report["removed_count"] == 0
    assert state["stage_path"].exists()
    assert state["stage_path"].read_bytes() == state["payload"]
    assert published_path.read_bytes() == b"corrupted published bytes"
    assert any(
        item["reason"] == "published bytes do not match the immutable audit row"
        for item in report["skipped"]
    )



def test_output_reconciler_never_follows_or_removes_temporary_symlinks(
    publication_setup,
):
    import os
    from datetime import timedelta

    from app.dataset_job_output_reconciliation import reconcile_dataset_job_output_files

    state = publication_setup
    temporary_dir = state["root"] / "published" / str(state["job"].id)
    temporary_dir.mkdir(parents=True, exist_ok=True)

    external_target = state["root"] / "outside-target.bin"
    external_target.write_bytes(b"must remain untouched")

    link = temporary_dir / (".promotion-" + "c" * 32 + ".tmp")
    link.symlink_to(external_target)

    old_timestamp = (models.utc_now() - timedelta(days=8)).timestamp()
    os.utime(link, (old_timestamp, old_timestamp), follow_symlinks=False)

    report = reconcile_dataset_job_output_files(
        state["db"],
        apply=True,
        grace_seconds=7 * 86400,
    )

    assert report["removed_count"] == 0
    assert link.is_symlink()
    assert external_target.read_bytes() == b"must remain untouched"
    assert not any(
        item["reference"] == f"published/{state['job'].id}/{link.name}"
        for item in report["temporary_candidates"]
    )
