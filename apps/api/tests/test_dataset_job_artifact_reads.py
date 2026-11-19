from datetime import timedelta
import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.config import settings
from app.database import Base
from app.dataset_job_artifact_reads import (
    DatasetJobSourceIneligible,
    DatasetJobSourceIntegrityError,
    DatasetJobSourceNotFound,
    read_dataset_job_source_bytes,
)
from app.dataset_job_leases import (
    DatasetJobLeaseLost,
    claim_next_dataset_job,
    enqueue_dataset_job,
)
from app.dataset_worker_credentials import (
    DatasetWorkerAuthorizationError,
    DatasetWorkerPrincipal,
    authenticate_dataset_worker,
    issue_dataset_worker_credential,
    revoke_dataset_worker_credential,
)


@pytest.fixture
def reader_setup(tmp_path, monkeypatch):
    root = tmp_path / "private-images"
    monkeypatch.setattr(settings, "image_storage_path", str(root))
    monkeypatch.setattr(settings, "max_image_upload_bytes", 50 * 1024 * 1024)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    store = models.Store(code="JOB-READ-STORE", name="Job read store")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Job read zone")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="JOB-READ-SHELF")
    db.add(shelf)
    db.flush()
    payload = b"approved private dataset source bytes"
    store_root = root / str(store.id)
    store_root.mkdir(parents=True)
    source_path = store_root / "source.bin"
    source_path.write_bytes(payload)
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="source.bin",
        storage_path=str(source_path),
        mime_type="application/octet-stream",
        file_size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        analysis_status="COMPLETED",
        retention_status="ACTIVE",
        legal_hold=False,
    )
    db.add(image)
    db.commit()
    source = {
        "shelf_image_id": image.id,
        "store_id": store.id,
        "source_image_sha256": image.sha256,
    }
    token, credential = issue_dataset_worker_credential(
        db,
        worker_id="dataset-reader",
        scopes=["jobs:claim", "artifacts:read"],
        expires_in_seconds=3600,
    )
    job = enqueue_dataset_job(
        db,
        idempotency_key="dataset-read-job",
        release_fingerprint="d" * 64,
        approval_evidence={
            "status": "APPROVED",
            "mode": "training",
            "record_sha256": "b" * 64,
            "gate_report_sha256": "c" * 64,
        },
        sources=[source],
    )
    claim = claim_next_dataset_job(db, worker_id="dataset-reader", lease_seconds=300)
    principal = authenticate_dataset_worker(db, bearer_token=token)
    yield {
        "db": db, "factory": factory, "engine": engine, "token": token,
        "principal": principal, "credential": credential, "job": job,
        "claim": claim, "image": image, "path": source_path, "payload": payload,
    }
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_worker_reads_only_approved_job_source_and_audits_exact_bytes(reader_setup):
    state = reader_setup
    result = read_dataset_job_source_bytes(
        state["db"], principal=state["principal"], job_id=state["job"].id,
        fencing_token=state["claim"].fencing_token,
        shelf_image_id=state["image"].id,
    )
    assert result == state["payload"]
    reads = state["db"].query(models.DatasetExecutionJobArtifactRead).filter_by(
        job_id=state["job"].id
    ).all()
    assert len(reads) == 1
    assert reads[0].worker_id == state["principal"].worker_id
    assert reads[0].credential_id == state["principal"].credential_id
    assert reads[0].fencing_token == state["claim"].fencing_token
    assert reads[0].source_image_sha256 == hashlib.sha256(result).hexdigest()
    assert reads[0].bytes_read == len(result)


def test_worker_cannot_read_an_image_not_in_the_job_source_set(reader_setup):
    state = reader_setup
    with pytest.raises(DatasetJobSourceNotFound):
        read_dataset_job_source_bytes(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token, shelf_image_id=999999,
        )
    assert state["db"].query(models.DatasetExecutionJobArtifactRead).count() == 0


def test_worker_source_read_requires_artifacts_read_scope(reader_setup):
    state = reader_setup
    principal = DatasetWorkerPrincipal(
        worker_id=state["principal"].worker_id,
        credential_id=state["principal"].credential_id,
        scopes=frozenset({"jobs:claim"}),
    )
    with pytest.raises(DatasetWorkerAuthorizationError):
        read_dataset_job_source_bytes(
            state["db"], principal=principal, job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token, shelf_image_id=state["image"].id,
        )
    assert state["db"].query(models.DatasetExecutionJobArtifactRead).count() == 0


def test_worker_source_read_requires_current_worker_and_fencing_token(reader_setup):
    state = reader_setup
    stale = DatasetWorkerPrincipal(
        worker_id="different-worker",
        credential_id=state["principal"].credential_id,
        scopes=state["principal"].scopes,
    )
    with pytest.raises(DatasetJobLeaseLost):
        read_dataset_job_source_bytes(
            state["db"], principal=stale, job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token, shelf_image_id=state["image"].id,
        )
    with pytest.raises(DatasetJobLeaseLost):
        read_dataset_job_source_bytes(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token + 1, shelf_image_id=state["image"].id,
        )
    assert state["db"].query(models.DatasetExecutionJobArtifactRead).count() == 0


def test_restricted_or_held_source_is_denied_without_audit(reader_setup):
    state = reader_setup
    state["image"].retention_status = "RESTRICTED"
    state["db"].commit()
    with pytest.raises(DatasetJobSourceIneligible):
        read_dataset_job_source_bytes(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token, shelf_image_id=state["image"].id,
        )
    assert state["db"].query(models.DatasetExecutionJobArtifactRead).count() == 0


def test_tampered_source_bytes_are_not_returned_or_audited(reader_setup):
    state = reader_setup
    state["path"].write_bytes(b"tampered source bytes")
    with pytest.raises(DatasetJobSourceIntegrityError):
        read_dataset_job_source_bytes(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token, shelf_image_id=state["image"].id,
        )
    assert state["db"].query(models.DatasetExecutionJobArtifactRead).count() == 0


def test_expired_lease_cannot_read_source_bytes(reader_setup):
    state = reader_setup
    state["job"].lease_expires_at = models.utc_now() - timedelta(seconds=1)
    state["db"].commit()
    with pytest.raises(DatasetJobLeaseLost):
        read_dataset_job_source_bytes(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token, shelf_image_id=state["image"].id,
        )
    assert state["db"].query(models.DatasetExecutionJobArtifactRead).count() == 0


def test_credential_revoked_after_http_authentication_is_rechecked_before_read(reader_setup):
    state = reader_setup
    state["db"].commit()
    with state["factory"]() as revoker:
        assert revoke_dataset_worker_credential(
            revoker, credential_id=state["principal"].credential_id
        )
    with pytest.raises(DatasetWorkerAuthorizationError):
        read_dataset_job_source_bytes(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token, shelf_image_id=state["image"].id,
        )
    assert state["db"].query(models.DatasetExecutionJobArtifactRead).count() == 0


def test_persisted_credential_scope_is_rechecked_not_trusted_from_principal(reader_setup):
    state = reader_setup
    state["db"].commit()
    credential = state["db"].query(models.DatasetWorkerCredential).filter_by(
        credential_id=state["principal"].credential_id
    ).one()
    credential.scopes = ["jobs:claim"]
    state["db"].commit()
    with pytest.raises(DatasetWorkerAuthorizationError):
        read_dataset_job_source_bytes(
            state["db"], principal=state["principal"], job_id=state["job"].id,
            fencing_token=state["claim"].fencing_token, shelf_image_id=state["image"].id,
        )
    assert state["db"].query(models.DatasetExecutionJobArtifactRead).count() == 0
