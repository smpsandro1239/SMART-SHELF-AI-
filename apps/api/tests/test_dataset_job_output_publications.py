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
    DatasetJobSourceIneligible,
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


@pytest.mark.parametrize(("retention_status", "legal_hold"), [("RESTRICTED", False), ("ACTIVE", True)])
def test_promotion_revalidates_sources_after_output_preparation(publication_setup, monkeypatch, retention_status, legal_hold):
    from app import dataset_job_output_publications as publications
    state = publication_setup
    original_prepare = publications._prepare_verified_bytes

    def prepare_then_restrict_source(**kwargs):
        result = original_prepare(**kwargs)
        source = state["db"].query(models.DatasetExecutionJobSource).filter_by(job_id=state["job"].id).one()
        image = state["db"].query(models.ShelfImage).filter_by(id=source.shelf_image_id).one()
        image.retention_status = retention_status
        image.legal_hold = legal_hold
        state["db"].commit()
        return result

    monkeypatch.setattr(publications, "_prepare_verified_bytes", prepare_then_restrict_source)
    with pytest.raises(DatasetJobSourceIneligible):
        promote_dataset_job_output(state["db"], principal=state["principal"], job_id=state["job"].id,
                                   fencing_token=state["claim"].fencing_token)
    assert state["db"].query(models.DatasetExecutionJobOutputPublication).count() == 0
    assert state["stage_path"].exists()
    published_root = state["root"] / "published"
    assert not list(published_root.rglob("*.artifact"))
    assert not list(published_root.rglob("*.tmp"))



@pytest.mark.parametrize(("retention_status", "legal_hold"), [("RESTRICTED", False), ("ACTIVE", True)])
def test_promotion_revalidates_every_source_not_only_first_source(
    publication_setup, monkeypatch, retention_status, legal_hold
):
    from app import dataset_job_output_publications as publications

    state = publication_setup
    db = state["db"]
    original_source = db.query(models.DatasetExecutionJobSource).filter_by(
        job_id=state["job"].id
    ).one()
    original_image = db.query(models.ShelfImage).filter_by(id=original_source.shelf_image_id).one()
    second_digest = hashlib.sha256(b"second immutable source").hexdigest()
    second_image = models.ShelfImage(
        shelf_id=original_image.shelf_id,
        original_filename="second-source.bin",
        storage_path="/not-read-by-this-test/second-source.bin",
        mime_type="application/octet-stream",
        file_size_bytes=22,
        sha256=second_digest,
        analysis_status="COMPLETED",
        retention_status="ACTIVE",
        legal_hold=False,
    )
    db.add(second_image)
    db.flush()
    second_image_id = second_image.id

    payload = b"multi-source model output fixture"
    digest = hashlib.sha256(payload).hexdigest()
    job = enqueue_dataset_job(
        db,
        idempotency_key=f"multi-source-output-{retention_status}-{legal_hold}",
        release_fingerprint="e" * 64,
        approval_evidence={
            "status": "APPROVED", "mode": "training",
            "record_sha256": "b" * 64, "gate_report_sha256": "c" * 64,
        },
        # Deliberately submit sources in reverse ID order. The eligibility
        # helper must lock and validate the complete set in stable ID order.
        sources=[
            {
                "shelf_image_id": second_image_id,
                "store_id": original_source.store_id,
                "source_image_sha256": second_digest,
            },
            {
                "shelf_image_id": original_source.shelf_image_id,
                "store_id": original_source.store_id,
                "source_image_sha256": original_source.source_image_sha256,
            },
        ],
    )
    claim = claim_next_dataset_job(db, worker_id=state["worker_id"], lease_seconds=300)
    assert claim is not None and claim.id == job.id
    stage_dir = state["root"] / "staging" / str(job.id) / str(claim.fencing_token)
    stage_dir.mkdir(parents=True)
    stage_path = stage_dir / "model.bin"
    stage_path.write_bytes(payload)
    complete_dataset_job(
        db,
        job_id=job.id,
        worker_id=state["worker_id"],
        fencing_token=claim.fencing_token,
        output_sha256=digest,
        staged_output_reference=f"staging/{job.id}/{claim.fencing_token}/model.bin",
    )
    original_prepare = publications._prepare_verified_bytes

    def prepare_then_restrict_second_source(**kwargs):
        result = original_prepare(**kwargs)
        image = db.query(models.ShelfImage).filter_by(id=second_image_id).one()
        image.retention_status = retention_status
        image.legal_hold = legal_hold
        db.commit()
        return result

    monkeypatch.setattr(
        publications, "_prepare_verified_bytes", prepare_then_restrict_second_source
    )
    with pytest.raises(DatasetJobSourceIneligible):
        promote_dataset_job_output(
            db,
            principal=state["principal"],
            job_id=job.id,
            fencing_token=claim.fencing_token,
        )

    assert db.query(models.DatasetExecutionJobOutputPublication).filter_by(
        job_id=job.id
    ).count() == 0
    assert stage_path.read_bytes() == payload
    assert not list((state["root"] / "published").rglob("*.artifact"))


def test_output_governance_events_are_ordered_and_state_is_derived(publication_setup):
    from app.dataset_output_governance import append_output_governance_event, get_output_governance_state

    state = publication_setup
    db = state["db"]
    publication = promote_dataset_job_output(
        db, principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    actor = models.User(
        email="output-governance-admin@example.test", store_id=None,
        full_name="Output Governance Admin",
        password_hash="test-only-not-a-real-password-hash", role="ADMIN", is_active=True,
    )
    db.add(actor)
    db.commit()

    def authorize(user, current_publication, event_type):
        return user.role == "ADMIN" and current_publication.id == publication.id and event_type in {
            "RESTRICTION_APPLIED", "RESTRICTION_RELEASED",
            "LEGAL_HOLD_APPLIED", "LEGAL_HOLD_RELEASED",
        }

    transitions = [
        ("RESTRICTION_APPLIED", True, False),
        ("LEGAL_HOLD_APPLIED", True, True),
        ("RESTRICTION_RELEASED", False, True),
        ("LEGAL_HOLD_RELEASED", False, False),
    ]
    for sequence, (event_type, restricted, legal_hold) in enumerate(transitions, start=1):
        event = append_output_governance_event(
            db, publication_id=publication.id, event_type=event_type,
            actor_user_id=actor.id, reason=f"Reviewed transition {sequence}",
            authorize=authorize, details={"case": f"TEST-{sequence}"},
        )
        assert event.sequence_number == sequence
        db.commit()
        projection = get_output_governance_state(db, publication_id=publication.id)
        assert projection.sequence_number == sequence
        assert projection.restricted is restricted
        assert projection.legal_hold is legal_hold
        assert projection.blocked is (restricted or legal_hold)


def test_output_governance_requires_explicit_authorization_and_valid_evidence(publication_setup):
    from app.dataset_output_governance import (
        DatasetOutputGovernanceAuthorizationError,
        DatasetOutputGovernanceError,
        append_output_governance_event,
    )

    state = publication_setup
    db = state["db"]
    publication = promote_dataset_job_output(
        db, principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    actor = models.User(
        email="output-governance-denied@example.test", store_id=None,
        full_name="Output Governance User",
        password_hash="test-only-not-a-real-password-hash", role="EMPLOYEE", is_active=True,
    )
    db.add(actor)
    db.commit()

    with pytest.raises(DatasetOutputGovernanceAuthorizationError):
        append_output_governance_event(
            db, publication_id=publication.id, event_type="RESTRICTION_APPLIED",
            actor_user_id=actor.id, reason="Request denied",
            authorize=lambda _actor, _publication, _action: False,
        )
    with pytest.raises(DatasetOutputGovernanceError, match="supplied together"):
        append_output_governance_event(
            db, publication_id=publication.id, event_type="RESTRICTION_APPLIED",
            actor_user_id=actor.id, reason="Evidence pair validation",
            authorize=lambda _actor, _publication, _action: True,
            evidence_reference="ticket://CASE-1",
        )
    with pytest.raises(DatasetOutputGovernanceError, match="non-whitespace"):
        append_output_governance_event(
            db, publication_id=publication.id, event_type="RESTRICTION_APPLIED",
            actor_user_id=actor.id, reason="   ",
            authorize=lambda _actor, _publication, _action: True,
        )
    assert db.query(models.DatasetExecutionJobOutputGovernanceEvent).count() == 0


def test_published_output_consumer_returns_verified_bytes(publication_setup):
    from app.dataset_job_output_consumption import consume_dataset_job_output_bytes

    state = publication_setup
    publication = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    payload = consume_dataset_job_output_bytes(
        state["db"], publication_id=publication.id,
        authorize=lambda _publication, _job: True,
    )
    assert payload == state["payload"]


def test_published_output_consumer_fails_closed_without_explicit_authorization(publication_setup):
    from app.dataset_job_output_consumption import (
        DatasetJobOutputAccessDenied, consume_dataset_job_output_bytes,
    )

    state = publication_setup
    publication = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    with pytest.raises(DatasetJobOutputAccessDenied):
        consume_dataset_job_output_bytes(
            state["db"], publication_id=publication.id, authorize=lambda _p, _j: None,
        )


@pytest.mark.parametrize("event_type", ["RESTRICTION_APPLIED", "LEGAL_HOLD_APPLIED"])
def test_published_output_consumer_blocks_governance_events(publication_setup, event_type):
    from app.dataset_job_output_consumption import (
        DatasetJobOutputAccessDenied, consume_dataset_job_output_bytes,
    )
    from app.dataset_output_governance import append_output_governance_event

    state = publication_setup
    publication = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    actor = models.User(
        email=f"governance-{event_type.lower()}@example.test",
        full_name="Governance Test Actor", password_hash="test-only-hash",
        role="ADMIN", is_active=True,
    )
    state["db"].add(actor)
    state["db"].flush()
    append_output_governance_event(
        state["db"], publication_id=publication.id, event_type=event_type,
        actor_user_id=actor.id, reason="Automated regression test",
        authorize=lambda _actor, _publication, _event: True,
    )
    state["db"].commit()
    with pytest.raises(DatasetJobOutputAccessDenied):
        consume_dataset_job_output_bytes(
            state["db"], publication_id=publication.id,
            authorize=lambda _publication, _job: True,
        )


@pytest.mark.parametrize(("retention_status", "legal_hold"), [("RESTRICTED", False), ("ACTIVE", True)])
def test_published_output_consumer_inherits_source_restrictions(
    publication_setup, retention_status, legal_hold,
):
    from app.dataset_job_output_consumption import (
        DatasetJobOutputAccessDenied, consume_dataset_job_output_bytes,
    )

    state = publication_setup
    publication = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    source = state["db"].query(models.DatasetExecutionJobSource).filter_by(
        job_id=state["job"].id
    ).one()
    image = state["db"].query(models.ShelfImage).filter_by(id=source.shelf_image_id).one()
    image.retention_status = retention_status
    image.legal_hold = legal_hold
    state["db"].commit()
    with pytest.raises(DatasetJobOutputAccessDenied):
        consume_dataset_job_output_bytes(
            state["db"], publication_id=publication.id,
            authorize=lambda _publication, _job: True,
        )


def test_published_output_consumer_rejects_tampered_bytes(publication_setup):
    from app.dataset_job_output_consumption import (
        DatasetJobOutputReadIntegrityError, consume_dataset_job_output_bytes,
    )

    state = publication_setup
    publication = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    path = state["root"] / publication.published_output_reference
    path.write_bytes(b"tampered output bytes")
    with pytest.raises(DatasetJobOutputReadIntegrityError):
        consume_dataset_job_output_bytes(
            state["db"], publication_id=publication.id,
            authorize=lambda _publication, _job: True,
        )


def test_published_output_consumer_rejects_symlink(publication_setup):
    from app.dataset_job_output_consumption import (
        DatasetJobOutputReadIntegrityError, consume_dataset_job_output_bytes,
    )

    state = publication_setup
    publication = promote_dataset_job_output(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    target = state["root"] / "outside-target.bin"
    target.write_bytes(state["payload"])
    published = state["root"] / publication.published_output_reference
    published.unlink()
    published.symlink_to(target)
    with pytest.raises(DatasetJobOutputReadIntegrityError):
        consume_dataset_job_output_bytes(
            state["db"], publication_id=publication.id,
            authorize=lambda _publication, _job: True,
        )
    assert target.read_bytes() == state["payload"]


def _create_second_published_output(
    state, *, suffix="derived", derived_from_publication_id=None,
    derivation_actor_user_id=None, derivation_reason=None, authorize_derivation=None,
):
    db = state["db"]
    source = db.query(models.DatasetExecutionJobSource).filter_by(job_id=state["job"].id).one()
    payload = f"derived output fixture {suffix}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    job = enqueue_dataset_job(
        db, idempotency_key=f"output-lineage-{suffix}", release_fingerprint=("f" if suffix == "derived" else "a") * 64,
        approval_evidence={
            "status": "APPROVED", "mode": "training",
            "record_sha256": "b" * 64, "gate_report_sha256": "c" * 64,
        },
        sources=[{
            "shelf_image_id": source.shelf_image_id,
            "store_id": source.store_id,
            "source_image_sha256": source.source_image_sha256,
        }],
    )
    claim = claim_next_dataset_job(db, worker_id=state["worker_id"], lease_seconds=300)
    assert claim is not None and claim.id == job.id
    stage_dir = state["root"] / "staging" / str(job.id) / str(claim.fencing_token)
    stage_dir.mkdir(parents=True)
    stage_path = stage_dir / "derived.bin"
    stage_path.write_bytes(payload)
    complete_dataset_job(
        db, job_id=job.id, worker_id=state["worker_id"],
        fencing_token=claim.fencing_token, output_sha256=digest,
        staged_output_reference=f"staging/{job.id}/{claim.fencing_token}/derived.bin",
    )
    publication = promote_dataset_job_output(
        db, principal=state["principal"], job_id=job.id,
        fencing_token=claim.fencing_token,
        derived_from_publication_id=derived_from_publication_id,
        derivation_actor_user_id=derivation_actor_user_id,
        derivation_reason=derivation_reason,
        authorize_derivation=authorize_derivation,
    )
    return publication, payload


def test_derived_output_inherits_parent_legal_hold_and_authorization(publication_setup):
    from app.dataset_job_output_consumption import (
        DatasetJobOutputAccessDenied, consume_dataset_job_output_bytes,
    )
    from app.dataset_output_governance import append_output_governance_event
    from app.dataset_output_lineage import (
        DatasetOutputLineageConflict, register_dataset_output_derivation,
    )

    state = publication_setup
    db = state["db"]
    parent = promote_dataset_job_output(
        db, principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
    )
    actor = models.User(
        email="output-lineage-admin@example.test", store_id=None,
        full_name="Output Lineage Admin",
        password_hash="test-only-hash", role="ADMIN", is_active=True,
    )
    db.add(actor)
    db.commit()

    derivation_reason = "Child output was produced from parent output"
    authorize_derivation = lambda user, parent_row, child_row: (
        user.role == "ADMIN" and parent_row.id == parent.id
        and child_row.job_id != parent.job_id
    )
    child, child_payload = _create_second_published_output(
        state,
        derived_from_publication_id=parent.id,
        derivation_actor_user_id=actor.id,
        derivation_reason=derivation_reason,
        authorize_derivation=authorize_derivation,
    )
    edge = db.query(models.DatasetExecutionJobOutputLineage).filter_by(
        parent_publication_id=parent.id, child_publication_id=child.id,
    ).one()
    assert edge.actor_user_id == actor.id and edge.reason == derivation_reason
    retried = promote_dataset_job_output(
        db, principal=state["principal"], job_id=child.job_id,
        fencing_token=child.fencing_token,
        derived_from_publication_id=parent.id,
        derivation_actor_user_id=actor.id,
        derivation_reason=derivation_reason,
        authorize_derivation=authorize_derivation,
    )
    assert retried.id == child.id

    with pytest.raises(DatasetOutputLineageConflict, match="cycle"):
        register_dataset_output_derivation(
            db, parent_publication_id=child.id, child_publication_id=parent.id,
            actor_user_id=actor.id, reason="Attempted reverse edge",
            authorize=lambda *_args: True,
        )
    db.rollback()

    append_output_governance_event(
        db, publication_id=parent.id, event_type="LEGAL_HOLD_APPLIED",
        actor_user_id=actor.id, reason="Preserve the parent and every derived output",
        authorize=lambda *_args: True,
    )
    db.commit()

    authorized_publications = []
    def authorize(publication, job):
        authorized_publications.append(publication.id)
        return True

    with pytest.raises(DatasetJobOutputAccessDenied, match="lineage is blocked"):
        consume_dataset_job_output_bytes(
            db, publication_id=child.id, authorize=authorize,
        )
    # The consumer fails immediately at the first blocked ancestor; it must
    # not continue authorizing or reading deeper nodes after a denial.
    assert parent.id in authorized_publications

    append_output_governance_event(
        db, publication_id=parent.id, event_type="LEGAL_HOLD_RELEASED",
        actor_user_id=actor.id, reason="Test fixture releases the hold after assertion",
        authorize=lambda *_args: True,
    )
    db.commit()
    authorized_publications.clear()
    assert consume_dataset_job_output_bytes(
        db, publication_id=child.id, authorize=authorize,
    ) == child_payload
    assert set(authorized_publications) == {parent.id, child.id}
