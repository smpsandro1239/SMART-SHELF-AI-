from datetime import timedelta
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app import models
from app.database import Base


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def build_restricted_image(db, storage_root: Path, *, with_detection: bool):
    store = models.Store(code="PURGE-TEST", name="Purge test store")
    db.add(store)
    db.flush()

    admin = models.User(
        email="purge-admin@example.test",
        full_name="Purge administrator",
        password_hash="test-only",
        role="ADMIN",
        is_active=True,
    )
    zone = models.Zone(store_id=store.id, name="Test zone")
    db.add_all([admin, zone])
    db.flush()

    shelf = models.Shelf(zone_id=zone.id, code="PURGE-SHELF")
    db.add(shelf)
    db.flush()

    store_directory = storage_root / str(store.id)
    store_directory.mkdir(parents=True, exist_ok=True)
    image_path = store_directory / "restricted.jpg"
    image_path.write_bytes(b"test-image")

    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="restricted.jpg",
        storage_path=str(image_path),
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256=hashlib.sha256(b"test-image").hexdigest(),
        analysis_status="COMPLETED",
        retention_status="RESTRICTED",
        retention_reason="Approved restriction for test",
        purge_not_before=models.utc_now() - timedelta(days=1),
        retention_policy_version="test-policy-v1",
    )
    db.add(image)
    db.flush()

    if with_detection:
        db.add(models.ShelfImageDetection(
            shelf_image_id=image.id,
            label="product",
            confidence=0.95,
            x_min=0.1,
            y_min=0.1,
            x_max=0.8,
            y_max=0.8,
            model_version="test-detector-v1",
        ))

    db.commit()
    return image.id, admin.id


def test_purge_preview_blocks_images_with_derived_evidence(db_session, tmp_path, monkeypatch):
    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=True
    )
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))

    result = main_module.get_shelf_image_purge_eligibility(
        image_id, request, db_session
    )

    assert result["eligible"] is False
    assert "derived_records_require_approved_disposition" in result["blockers"]
    assert result["derived_records"]["detections"] == 1
    assert result["deletion_performed"] is False
    assert (tmp_path / "1" / "restricted.jpg").exists()


def test_purge_preview_blocks_file_integrity_mismatch(db_session, tmp_path, monkeypatch):
    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    image = db_session.get(models.ShelfImage, image_id)
    image.sha256 = "b" * 64
    db_session.commit()
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))

    result = main_module.get_shelf_image_purge_eligibility(
        image_id, request, db_session
    )

    assert result["eligible"] is False
    assert result["internal_checks_passed"] is False
    assert "stored_file_integrity_mismatch" in result["blockers"]
    assert "external_artifact_disposition_not_verified" in result["blockers"]
    assert result["stored_file_available"] is True
    assert result["stored_file_integrity_verified"] is False
    assert result["deletion_performed"] is False
    assert (tmp_path / "1" / "restricted.jpg").exists()


def test_purge_preview_allows_only_clean_scheduled_candidate(db_session, tmp_path, monkeypatch):
    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))

    result = main_module.get_shelf_image_purge_eligibility(
        image_id, request, db_session
    )

    assert result["eligible"] is False
    assert result["internal_checks_passed"] is True
    assert result["blockers"] == ["external_artifact_disposition_not_verified"]
    assert result["stored_file_integrity_verified"] is True
    assert result["derived_records"]["detections"] == 0
    assert result["derived_records"]["ocr_runs"] == 0
    assert result["derived_records"]["embedding_exemplars"] == 0
    assert result["deletion_performed"] is False
    assert (tmp_path / "1" / "restricted.jpg").exists()



def test_external_artifact_reference_registration_is_idempotent(db_session, tmp_path, monkeypatch):
    from app.schemas import ShelfImageArtifactReferenceCreate

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    payload = ShelfImageArtifactReferenceCreate(
        artifact_type="DATASET_RELEASE",
        external_system="offline-dataset-registry",
        external_reference="releases/ds-2026-11-15",
        release_id="ds-2026-11-15",
        sha256="a" * 64,
    )

    first = main_module.register_shelf_image_artifact_reference(
        image_id, payload, request, db_session
    )
    second = main_module.register_shelf_image_artifact_reference(
        image_id, payload, request, db_session
    )

    assert first.id == second.id
    assert first.store_id == 1
    assert first.artifact_type == "DATASET_RELEASE"
    assert first.sha256 == "a" * 64
    assert db_session.query(models.ShelfImageArtifactReference).count() == 1


def test_external_artifact_reference_rejects_conflicting_duplicate(db_session, tmp_path):
    from fastapi import HTTPException
    from app.schemas import ShelfImageArtifactReferenceCreate

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    first_payload = ShelfImageArtifactReferenceCreate(
        artifact_type="BACKUP",
        external_system="backup-vault",
        external_reference="backup/object/123",
        sha256="a" * 64,
    )
    conflicting_payload = ShelfImageArtifactReferenceCreate(
        artifact_type="BACKUP",
        external_system="backup-vault",
        external_reference="backup/object/123",
        sha256="b" * 64,
    )

    main_module.register_shelf_image_artifact_reference(
        image_id, first_payload, request, db_session
    )
    with pytest.raises(HTTPException) as exc:
        main_module.register_shelf_image_artifact_reference(
            image_id, conflicting_payload, request, db_session
        )

    assert exc.value.status_code == 409
    assert db_session.query(models.ShelfImageArtifactReference).count() == 1


def test_artifact_reference_is_visible_in_purge_preview_but_never_authorizes_deletion(
    db_session, tmp_path, monkeypatch
):
    from app.schemas import ShelfImageArtifactReferenceCreate

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    main_module.register_shelf_image_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="OBJECT_REPLICA",
            external_system="object-storage",
            external_reference="bucket-a/object-987",
        ),
        request,
        db_session,
    )
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))

    preview = main_module.get_shelf_image_purge_eligibility(
        image_id, request, db_session
    )

    assert preview["eligible"] is False
    assert "external_artifact_disposition_not_verified" in preview["blockers"]
    assert preview["declared_external_artifact_references"] == 1
    assert preview["deletion_performed"] is False
    assert (tmp_path / "1" / "restricted.jpg").exists()



def test_external_artifact_registration_rejects_purged_image(db_session, tmp_path):
    from fastapi import HTTPException
    from app.schemas import ShelfImageArtifactReferenceCreate

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    image = db_session.get(models.ShelfImage, image_id)
    image.retention_status = "PURGED"
    db_session.commit()
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    payload = ShelfImageArtifactReferenceCreate(
        artifact_type="BACKUP",
        external_system="backup-vault",
        external_reference="backup/object-after-purge",
    )

    with pytest.raises(HTTPException) as exc:
        main_module.register_shelf_image_artifact_reference(
            image_id, payload, request, db_session
        )

    assert exc.value.status_code == 409
    assert db_session.query(models.ShelfImageArtifactReference).count() == 0



def test_artifact_disposition_requires_two_person_approval_and_evidence(db_session, tmp_path):
    from fastapi import HTTPException
    from app.schemas import (
        ShelfImageArtifactReferenceCreate,
        ShelfImageArtifactDispositionActionRequest,
    )

    image_id, first_admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    second_admin = models.User(
        email="second-purge-admin@example.test",
        full_name="Second administrator",
        password_hash="test-only",
        role="ADMIN",
        is_active=True,
    )
    db_session.add(second_admin)
    db_session.commit()
    second_admin_id = second_admin.id

    artifact = main_module.register_shelf_image_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="BACKUP",
            external_system="backup-vault",
            external_reference="backup/retention/object-1",
        ),
        SimpleNamespace(state=SimpleNamespace(user_id=first_admin_id)),
        db_session,
    )
    first_request = SimpleNamespace(state=SimpleNamespace(user_id=first_admin_id))
    second_request = SimpleNamespace(state=SimpleNamespace(user_id=second_admin_id))

    proposed = main_module.create_shelf_image_artifact_disposition_event(
        image_id,
        artifact.id,
        ShelfImageArtifactDispositionActionRequest(
            action="PROPOSE",
            reason="Backup retention period has expired",
        ),
        first_request,
        db_session,
    )
    assert proposed.event_type == "PROPOSED"

    with pytest.raises(HTTPException) as self_approval:
        main_module.create_shelf_image_artifact_disposition_event(
            image_id,
            artifact.id,
            ShelfImageArtifactDispositionActionRequest(
                action="APPROVE",
                reason="Attempted self approval",
            ),
            first_request,
            db_session,
        )
    assert self_approval.value.status_code == 409

    approved = main_module.create_shelf_image_artifact_disposition_event(
        image_id,
        artifact.id,
        ShelfImageArtifactDispositionActionRequest(
            action="APPROVE",
            reason="Independent review completed",
        ),
        second_request,
        db_session,
    )
    assert approved.event_type == "APPROVED"

    with pytest.raises(HTTPException) as missing_evidence:
        main_module.create_shelf_image_artifact_disposition_event(
            image_id,
            artifact.id,
            ShelfImageArtifactDispositionActionRequest(
                action="ATTEST_DISPOSED",
                reason="External backup removal reported",
            ),
            first_request,
            db_session,
        )
    assert missing_evidence.value.status_code == 422

    with pytest.raises(HTTPException) as approver_attests:
        main_module.create_shelf_image_artifact_disposition_event(
            image_id,
            artifact.id,
            ShelfImageArtifactDispositionActionRequest(
                action="ATTEST_DISPOSED",
                reason="Same reviewer cannot attest completion",
                evidence_reference="ticket/cleanup-1",
                evidence_sha256="a" * 64,
            ),
            second_request,
            db_session,
        )
    assert approver_attests.value.status_code == 409

    attested = main_module.create_shelf_image_artifact_disposition_event(
        image_id,
        artifact.id,
        ShelfImageArtifactDispositionActionRequest(
            action="ATTEST_DISPOSED",
            reason="External backup removal evidence recorded",
            evidence_reference="ticket/cleanup-1",
            evidence_sha256="a" * 64,
        ),
        first_request,
        db_session,
    )
    assert attested.event_type == "DISPOSAL_ATTESTED"
    assert attested.evidence_sha256 == "a" * 64

    history = main_module.list_shelf_image_artifact_disposition_events(
        image_id, artifact.id, first_request, db_session
    )
    assert [event.event_type for event in history] == [
        "PROPOSED", "APPROVED", "DISPOSAL_ATTESTED"
    ]


def test_rejected_artifact_disposition_can_be_reproposed(db_session, tmp_path):
    from app.schemas import (
        ShelfImageArtifactReferenceCreate,
        ShelfImageArtifactDispositionActionRequest,
    )

    image_id, first_admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    second_admin = models.User(
        email="review-admin@example.test",
        full_name="Review administrator",
        password_hash="test-only",
        role="ADMIN",
        is_active=True,
    )
    db_session.add(second_admin)
    db_session.commit()
    first_request = SimpleNamespace(state=SimpleNamespace(user_id=first_admin_id))
    second_request = SimpleNamespace(state=SimpleNamespace(user_id=second_admin.id))
    artifact = main_module.register_shelf_image_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="CACHE",
            external_system="edge-cache",
            external_reference="cache/key-42",
        ),
        first_request,
        db_session,
    )

    main_module.create_shelf_image_artifact_disposition_event(
        image_id, artifact.id,
        ShelfImageArtifactDispositionActionRequest(
            action="PROPOSE", reason="Request cache purge",
        ),
        first_request, db_session,
    )
    rejected = main_module.create_shelf_image_artifact_disposition_event(
        image_id, artifact.id,
        ShelfImageArtifactDispositionActionRequest(
            action="REJECT", reason="Cache still required by active release",
        ),
        second_request, db_session,
    )
    assert rejected.event_type == "REJECTED"

    reproposed = main_module.create_shelf_image_artifact_disposition_event(
        image_id, artifact.id,
        ShelfImageArtifactDispositionActionRequest(
            action="PROPOSE", reason="New evidence confirms cache is obsolete",
        ),
        first_request, db_session,
    )
    assert reproposed.event_type == "PROPOSED"
