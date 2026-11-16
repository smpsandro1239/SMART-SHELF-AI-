from datetime import datetime, timedelta, timezone
import hashlib
import json
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
    store_number = db.query(models.Store).count() + 1
    store = models.Store(code=f"PURGE-TEST-{store_number}", name="Purge test store")
    db.add(store)
    db.flush()

    admin = models.User(
        email=f"purge-admin-{store_number}@example.test",
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


def register_test_external_integration(db_session, image_id, admin_id, external_system):
    image = db_session.get(models.ShelfImage, image_id)
    store_id = (
        db_session.query(models.Zone.store_id)
        .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == image.shelf_id)
        .scalar()
    )
    db_session.add(models.StoreExternalIntegration(
        store_id=store_id,
        external_system=external_system,
        provider="test-provider",
        status="ACTIVE",
        required_for_retention=False,
        capabilities=["inventory"],
        last_seen_at=models.utc_now(),
        created_by_user_id=admin_id,
        updated_by_user_id=admin_id,
    ))
    db_session.commit()
    return store_id


def register_test_artifact_reference(image_id, payload, request, db_session):
    """Register the store-scoped test connector before exercising the API."""
    image = db_session.get(models.ShelfImage, image_id)
    store_id = (
        db_session.query(models.Zone.store_id)
        .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == image.shelf_id)
        .scalar()
    )
    integration = db_session.query(models.StoreExternalIntegration).filter_by(
        store_id=store_id, external_system=payload.external_system
    ).first()
    if integration is None:
        register_test_external_integration(
            db_session, image_id, request.state.user_id, payload.external_system
        )
    return main_module.register_shelf_image_artifact_reference(
        image_id, payload, request, db_session
    )


def test_restore_cancels_existing_purge_schedule_and_records_audit(db_session, tmp_path):
    from app.schemas import ShelfImageRetentionRequest

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    image = db_session.get(models.ShelfImage, image_id)
    previous_purge_date = image.purge_not_before
    assert previous_purge_date is not None
    assert image.retention_policy_version == "test-policy-v1"

    restored = main_module.restore_shelf_image(
        image_id,
        ShelfImageRetentionRequest(reason="Restore image for renewed operational use"),
        request,
        db_session,
    )

    assert restored.retention_status == "ACTIVE"
    assert restored.purge_not_before is None
    assert restored.retention_policy_version is None
    events = db_session.query(models.ShelfImageRetentionEvent).filter_by(
        shelf_image_id=image_id
    ).order_by(models.ShelfImageRetentionEvent.id).all()
    assert [event.event_type for event in events] == ["PURGE_CANCELLED", "RESTORED"]
    assert previous_purge_date.isoformat() in events[0].reason
    assert events[0].from_status == events[0].to_status == "RESTRICTED"
    assert events[1].from_status == "RESTRICTED"
    assert events[1].to_status == "ACTIVE"


def test_restore_clears_orphaned_purge_policy_without_scheduled_date(db_session, tmp_path):
    from app.schemas import ShelfImageRetentionRequest

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    image = db_session.get(models.ShelfImage, image_id)
    image.purge_not_before = None
    image.retention_policy_version = "stale-policy-v0"
    db_session.commit()

    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    restored = main_module.restore_shelf_image(
        image_id,
        ShelfImageRetentionRequest(reason="Restore image after metadata repair"),
        request,
        db_session,
    )

    assert restored.retention_status == "ACTIVE"
    assert restored.purge_not_before is None
    assert restored.retention_policy_version is None
    events = db_session.query(models.ShelfImageRetentionEvent).filter_by(
        shelf_image_id=image_id
    ).order_by(models.ShelfImageRetentionEvent.id).all()
    assert [event.event_type for event in events] == ["PURGE_CANCELLED", "RESTORED"]
    assert "date=missing" in events[0].reason
    assert "policy=stale-policy-v0" in events[0].reason


def test_retention_state_transitions_refresh_locked_image_rows(db_session, tmp_path, monkeypatch):
    from sqlalchemy.orm import Query
    from app.schemas import ShelfImageRetentionRequest

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    refreshed_image_locks = []
    original_populate_existing = Query.populate_existing

    def recording_populate_existing(query):
        if any(
            description.get("entity") is models.ShelfImage
            for description in query.column_descriptions
        ):
            refreshed_image_locks.append(models.ShelfImage)
        return original_populate_existing(query)

    monkeypatch.setattr(Query, "populate_existing", recording_populate_existing)

    payload = ShelfImageRetentionRequest(reason="Retention transition consistency test")
    main_module.apply_shelf_image_legal_hold(image_id, payload, request, db_session)
    main_module.release_shelf_image_legal_hold(image_id, payload, request, db_session)
    main_module.cancel_shelf_image_purge_schedule(image_id, payload, request, db_session)
    main_module.restore_shelf_image(image_id, payload, request, db_session)
    restricted = main_module.restrict_shelf_image(image_id, payload, request, db_session)

    assert restricted.retention_status == "RESTRICTED"
    assert len(refreshed_image_locks) == 5


def test_legal_hold_blocks_overdue_purge_until_hold_is_released(db_session, tmp_path, monkeypatch):
    from app.schemas import ShelfImageRetentionRequest

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    payload = ShelfImageRetentionRequest(reason="Preserve image for legal review")

    held = main_module.apply_shelf_image_legal_hold(
        image_id, payload, request, db_session
    )
    assert held.legal_hold is True

    held_preview = main_module.get_shelf_image_purge_eligibility(
        image_id, request, db_session
    )
    assert held_preview["eligible"] is False
    assert "legal_hold_active" in held_preview["blockers"]
    assert held_preview["deletion_performed"] is False

    released = main_module.release_shelf_image_legal_hold(
        image_id,
        ShelfImageRetentionRequest(reason="Legal review completed"),
        request,
        db_session,
    )
    assert released.legal_hold is False

    released_preview = main_module.get_shelf_image_purge_eligibility(
        image_id, request, db_session
    )
    assert "legal_hold_active" not in released_preview["blockers"]
    assert released_preview["eligible"] is False
    assert released_preview["deletion_performed"] is False
    assert (tmp_path / "1" / "restricted.jpg").exists()


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
    assert result["blockers"] == [
        "external_artifact_disposition_not_verified",
        "purge_executor_not_implemented",
    ]
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

    first = register_test_artifact_reference(
        image_id, payload, request, db_session
    )
    second = register_test_artifact_reference(
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

    register_test_artifact_reference(
        image_id, first_payload, request, db_session
    )
    with pytest.raises(HTTPException) as exc:
        register_test_artifact_reference(
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
    register_test_artifact_reference(
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
        register_test_artifact_reference(
            image_id, payload, request, db_session
        )

    assert exc.value.status_code == 409
    assert db_session.query(models.ShelfImageArtifactReference).count() == 0



def test_artifact_disposition_requires_two_person_approval_and_evidence(db_session, tmp_path, monkeypatch):
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

    artifact = register_test_artifact_reference(
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
    assert [event.sequence_number for event in history] == [1, 2, 3]
    assert [event.actor_user_id for event in history] == [
        first_admin_id, second_admin_id, first_admin_id
    ]

    # A second artifact deliberately starts at sequence 1. The purge preview
    # must join latest events by both artifact ID and sequence, never sequence alone.
    second_artifact = register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="CACHE",
            external_system="edge-cache",
            external_reference="cache/independent-object",
        ),
        first_request,
        db_session,
    )
    second_proposal = main_module.create_shelf_image_artifact_disposition_event(
        image_id,
        second_artifact.id,
        ShelfImageArtifactDispositionActionRequest(
            action="PROPOSE",
            reason="Request independent cache disposition",
        ),
        second_request,
        db_session,
    )
    assert second_proposal.sequence_number == 1

    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    preview = main_module.get_shelf_image_purge_eligibility(
        image_id, first_request, db_session
    )
    assert preview["eligible"] is False
    assert "external_artifact_disposition_not_verified" in preview["blockers"]
    assert preview["declared_external_artifact_references"] == 2
    assert preview["external_artifact_disposition"]["disposal_attested"] == 1
    assert preview["external_artifact_disposition"]["proposed"] == 1
    assert preview["external_artifact_disposition"]["without_final_disposition"] == 1
    assert preview["deletion_performed"] is False


def test_rejected_artifact_disposition_can_be_reproposed(db_session, tmp_path, monkeypatch):
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
    artifact = register_test_artifact_reference(
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

    unreviewed = register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="REPORT",
            external_system="audit-system",
            external_reference="reports/retention-audit-2",
        ),
        first_request,
        db_session,
    )
    assert unreviewed.id != artifact.id

    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    preview = main_module.get_shelf_image_purge_eligibility(
        image_id, first_request, db_session
    )
    assert preview["declared_external_artifact_references"] == 2
    assert preview["external_artifact_disposition"]["proposed"] == 1
    assert preview["external_artifact_disposition"]["without_final_disposition"] == 2
    assert preview["eligible"] is False
    assert "external_artifact_disposition_not_verified" in preview["blockers"]


def test_signed_inventory_snapshot_verifies_exact_coverage_and_keeps_purge_disabled(
    db_session, tmp_path, monkeypatch
):
    from app.artifact_inventory_signing import inventory_signature
    from app.schemas import (
        ShelfImageArtifactReferenceCreate,
        ShelfImageArtifactDispositionActionRequest,
        ShelfImageArtifactInventorySnapshotCreate,
    )

    image_id, first_admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    second_admin = models.User(
        email="inventory-reviewer@example.test",
        full_name="Inventory reviewer",
        password_hash="test-only",
        role="ADMIN",
        is_active=True,
    )
    db_session.add(second_admin)
    db_session.commit()
    first_request = SimpleNamespace(state=SimpleNamespace(user_id=first_admin_id))
    second_request = SimpleNamespace(state=SimpleNamespace(user_id=second_admin.id))
    register_test_external_integration(
        db_session, image_id, first_admin_id, "backup-vault"
    )

    artifact = register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="BACKUP",
            external_system="backup-vault",
            external_reference="backup/image-1",
            sha256="a" * 64,
        ),
        first_request,
        db_session,
    )
    main_module.create_shelf_image_artifact_disposition_event(
        image_id, artifact.id,
        ShelfImageArtifactDispositionActionRequest(
            action="PROPOSE", reason="Request verified backup removal",
        ),
        first_request, db_session,
    )
    main_module.create_shelf_image_artifact_disposition_event(
        image_id, artifact.id,
        ShelfImageArtifactDispositionActionRequest(
            action="APPROVE", reason="Independent approval of backup removal",
        ),
        second_request, db_session,
    )
    main_module.create_shelf_image_artifact_disposition_event(
        image_id, artifact.id,
        ShelfImageArtifactDispositionActionRequest(
            action="ATTEST_DISPOSED",
            reason="Backup provider confirms object removal",
            evidence_reference="ticket/backup-removal-1",
            evidence_sha256="b" * 64,
        ),
        first_request, db_session,
    )

    secret = "test-backup-vault-inventory-secret-32-bytes"
    monkeypatch.setattr(
        main_module.settings,
        "artifact_inventory_hmac_keys_json",
        json.dumps({"backup-vault": secret}),
    )
    generated_at = datetime.now(timezone.utc)
    entries = [{
        "artifact_type": "BACKUP",
        "external_reference": "backup/image-1",
        "sha256": "a" * 64,
        "state": "ABSENT",
    }]
    signature = inventory_signature(
        image_id=image_id,
        store_id=artifact.store_id,
        external_system="backup-vault",
        snapshot_id="snapshot-image-1",
        generated_at=generated_at,
        entries=entries,
        secret=secret,
        inventory_complete=True,
    )
    snapshot = main_module.create_shelf_image_artifact_inventory_snapshot(
        image_id,
        ShelfImageArtifactInventorySnapshotCreate(
            external_system="backup-vault",
            snapshot_id="snapshot-image-1",
            generated_at=generated_at,
            inventory_complete=True,
            entries=entries,
            signature=signature,
        ),
        first_request,
        db_session,
    )
    assert snapshot.artifact_count == 1
    assert snapshot.present_count == 0
    assert snapshot.absent_count == 1
    assert len(snapshot.manifest_sha256) == 64

    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    preview = main_module.get_shelf_image_purge_eligibility(
        image_id, first_request, db_session
    )
    assert preview["external_artifact_inventory"]["verified_systems"] == ["backup-vault"]
    assert preview["external_artifact_inventory"]["unverified_systems"] == []
    assert preview["internal_checks_passed"] is True
    assert "external_artifact_disposition_not_verified" not in preview["blockers"]
    assert "purge_executor_not_implemented" in preview["blockers"]
    assert preview["eligible"] is False
    assert preview["deletion_performed"] is False
    assert (tmp_path / "1" / "restricted.jpg").exists()

    # A reference added after the signed snapshot invalidates exact coverage.
    register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="CACHE",
            external_system="backup-vault",
            external_reference="backup/new-object-after-snapshot",
        ),
        first_request,
        db_session,
    )
    changed_preview = main_module.get_shelf_image_purge_eligibility(
        image_id, first_request, db_session
    )
    assert changed_preview["external_artifact_inventory"]["unverified_systems"] == [
        "backup-vault"
    ]
    assert "external_artifact_disposition_not_verified" in changed_preview["blockers"]
    assert changed_preview["eligible"] is False


def test_signed_inventory_snapshot_rejects_incomplete_or_invalid_source_evidence(
    db_session, tmp_path, monkeypatch
):
    from fastapi import HTTPException
    from app.artifact_inventory_signing import inventory_signature
    from app.schemas import (
        ShelfImageArtifactReferenceCreate,
        ShelfImageArtifactInventorySnapshotCreate,
    )

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    register_test_external_integration(
        db_session, image_id, admin_id, "edge-cache"
    )
    artifact = register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="CACHE",
            external_system="edge-cache",
            external_reference="cache/image-1",
        ),
        request,
        db_session,
    )
    secret = "test-edge-cache-inventory-secret-32-bytes"
    monkeypatch.setattr(
        main_module.settings,
        "artifact_inventory_hmac_keys_json",
        json.dumps({"edge-cache": secret}),
    )
    generated_at = datetime.now(timezone.utc)
    incomplete_entries = [{
        "artifact_type": "CACHE",
        "external_reference": "cache/unknown-object",
        "sha256": None,
        "state": "PRESENT",
    }]
    signature = inventory_signature(
        image_id=image_id,
        store_id=artifact.store_id,
        external_system="edge-cache",
        snapshot_id="snapshot-incomplete",
        generated_at=generated_at,
        entries=incomplete_entries,
        secret=secret,
        inventory_complete=True,
    )
    with pytest.raises(HTTPException) as incomplete:
        main_module.create_shelf_image_artifact_inventory_snapshot(
            image_id,
            ShelfImageArtifactInventorySnapshotCreate(
                external_system="edge-cache",
                snapshot_id="snapshot-incomplete",
                generated_at=generated_at,
                inventory_complete=True,
                entries=incomplete_entries,
                signature=signature,
            ),
            request,
            db_session,
        )
    assert incomplete.value.status_code == 409

    exact_entries = [{
        "artifact_type": "CACHE",
        "external_reference": "cache/image-1",
        "sha256": None,
        "state": "PRESENT",
    }]
    valid_signature = inventory_signature(
        image_id=image_id,
        store_id=artifact.store_id,
        external_system="edge-cache",
        snapshot_id="snapshot-invalid-signature",
        generated_at=generated_at,
        entries=exact_entries,
        secret=secret,
        inventory_complete=True,
    )
    with pytest.raises(HTTPException) as invalid_signature:
        main_module.create_shelf_image_artifact_inventory_snapshot(
            image_id,
            ShelfImageArtifactInventorySnapshotCreate(
                external_system="edge-cache",
                snapshot_id="snapshot-invalid-signature",
                generated_at=generated_at,
                inventory_complete=True,
                entries=exact_entries,
                signature="0" * 64 if valid_signature != "0" * 64 else "1" * 64,
            ),
            request,
            db_session,
        )
    assert invalid_signature.value.status_code == 401


def test_purge_preview_requires_every_retention_integration_to_be_covered(
    db_session, tmp_path, monkeypatch
):
    from app.schemas import ShelfImageArtifactReferenceCreate

    image_id, admin_id = build_restricted_image(db_session, tmp_path, with_detection=False)
    image = db_session.get(models.ShelfImage, image_id)
    store_id = db_session.query(models.Zone.store_id).join(
        models.Shelf, models.Shelf.zone_id == models.Zone.id
    ).filter(models.Shelf.id == image.shelf_id).scalar()
    db_session.add(models.StoreExternalIntegration(
        store_id=store_id, external_system="required-backup-vault",
        provider="test-provider", status="ACTIVE", required_for_retention=True,
        capabilities=["inventory"], last_seen_at=models.utc_now(),
        created_by_user_id=admin_id, updated_by_user_id=admin_id,
    ))
    db_session.commit()

    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="CACHE", external_system="optional-cache",
            external_reference="cache/object-1",
        ),
        request, db_session,
    )
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    preview = main_module.get_shelf_image_purge_eligibility(image_id, request, db_session)

    assert preview["eligible"] is False
    assert "required_integration_missing_image_artifacts:required-backup-vault" in preview["external_artifact_inventory"]["unverified_systems"]
    assert "external_artifact_disposition_not_verified" in preview["blockers"]
    assert preview["deletion_performed"] is False
    assert (tmp_path / str(store_id) / "restricted.jpg").exists()


def test_purge_preview_rejects_revoked_declared_artifact_integration(
    db_session, tmp_path, monkeypatch
):
    from app.schemas import ShelfImageArtifactReferenceCreate

    image_id, admin_id = build_restricted_image(db_session, tmp_path, with_detection=False)
    image = db_session.get(models.ShelfImage, image_id)
    store_id = db_session.query(models.Zone.store_id).join(
        models.Shelf, models.Shelf.zone_id == models.Zone.id
    ).filter(models.Shelf.id == image.shelf_id).scalar()
    db_session.add(models.StoreExternalIntegration(
        store_id=store_id, external_system="revoked-storage",
        provider="test-provider", status="ACTIVE", required_for_retention=False,
        capabilities=["inventory"], created_by_user_id=admin_id,
        updated_by_user_id=admin_id,
    ))
    db_session.commit()

    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="BACKUP", external_system="revoked-storage",
            external_reference="bucket/object-2",
        ),
        request, db_session,
    )
    integration = db_session.query(models.StoreExternalIntegration).filter_by(
        store_id=store_id, external_system="revoked-storage"
    ).one()
    integration.status = "REVOKED"
    db_session.commit()
    integration = db_session.query(models.StoreExternalIntegration).filter_by(
        store_id=store_id, external_system="revoked-storage"
    ).one()
    integration.status = "REVOKED"
    db_session.commit()
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    preview = main_module.get_shelf_image_purge_eligibility(image_id, request, db_session)

    assert preview["eligible"] is False
    assert "artifact_integration_inactive_or_missing:revoked-storage" in preview["external_artifact_inventory"]["unverified_systems"]
    assert "external_artifact_disposition_not_verified" in preview["blockers"]
    assert preview["deletion_performed"] is False

def test_artifact_lineage_registration_persists_same_image_parent(db_session, tmp_path):
    from app.schemas import ShelfImageArtifactReferenceCreate

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    parent = register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="BACKUP",
            external_system="primary-store",
            external_reference="objects/source.zip",
            sha256="a" * 64,
        ),
        request,
        db_session,
    )
    child = register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="DATASET_RELEASE",
            external_system="archive-store",
            external_reference="releases/derived.zip",
            parent_reference_id=parent.id,
            sha256="b" * 64,
        ),
        request,
        db_session,
    )

    assert child.parent_reference_id == parent.id
    assert child.shelf_image_id == parent.shelf_image_id == image_id
    assert child.store_id == parent.store_id


def test_artifact_lineage_registration_rejects_missing_parent(db_session, tmp_path):
    from fastapi import HTTPException
    from app.schemas import ShelfImageArtifactReferenceCreate

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    payload = ShelfImageArtifactReferenceCreate(
        artifact_type="DATASET_RELEASE",
        external_system="archive-store",
        external_reference="releases/orphan.zip",
        parent_reference_id=999999,
    )

    with pytest.raises(HTTPException) as exc:
        register_test_artifact_reference(
            image_id, payload, request, db_session
        )

    assert exc.value.status_code == 422
    assert db_session.query(models.ShelfImageArtifactReference).count() == 0


def test_artifact_lineage_registration_rejects_parent_from_another_image_or_store(
    db_session, tmp_path
):
    from fastapi import HTTPException
    from app.schemas import ShelfImageArtifactReferenceCreate

    first_image_id, first_admin_id = build_restricted_image(
        db_session, tmp_path / "first", with_detection=False
    )
    second_image_id, _ = build_restricted_image(
        db_session, tmp_path / "second", with_detection=False
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=first_admin_id))
    parent = register_test_artifact_reference(
        first_image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="BACKUP",
            external_system="primary-store",
            external_reference="objects/other-image.zip",
        ),
        request,
        db_session,
    )

    with pytest.raises(HTTPException) as exc:
        register_test_artifact_reference(
            second_image_id,
            ShelfImageArtifactReferenceCreate(
                artifact_type="DATASET_RELEASE",
                external_system="archive-store",
                external_reference="releases/cross-image.zip",
                parent_reference_id=parent.id,
            ),
            request,
            db_session,
        )

    assert exc.value.status_code == 422
    assert db_session.query(models.ShelfImageArtifactReference).count() == 1


def test_artifact_lineage_registration_is_idempotent_only_for_same_parent(
    db_session, tmp_path
):
    from fastapi import HTTPException
    from app.schemas import ShelfImageArtifactReferenceCreate

    image_id, admin_id = build_restricted_image(
        db_session, tmp_path, with_detection=False
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    parent_a = register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="BACKUP",
            external_system="primary-store",
            external_reference="objects/source-a.zip",
        ),
        request,
        db_session,
    )
    parent_b = register_test_artifact_reference(
        image_id,
        ShelfImageArtifactReferenceCreate(
            artifact_type="BACKUP",
            external_system="primary-store",
            external_reference="objects/source-b.zip",
        ),
        request,
        db_session,
    )
    child_payload = ShelfImageArtifactReferenceCreate(
        artifact_type="DATASET_RELEASE",
        external_system="archive-store",
        external_reference="releases/shared.zip",
        parent_reference_id=parent_a.id,
        sha256="c" * 64,
    )
    first = register_test_artifact_reference(
        image_id, child_payload, request, db_session
    )
    replay = register_test_artifact_reference(
        image_id, child_payload, request, db_session
    )

    assert replay.id == first.id
    assert replay.parent_reference_id == parent_a.id

    conflicting_lineage = ShelfImageArtifactReferenceCreate(
        artifact_type="DATASET_RELEASE",
        external_system="archive-store",
        external_reference="releases/shared.zip",
        parent_reference_id=parent_b.id,
        sha256="c" * 64,
    )
    with pytest.raises(HTTPException) as exc:
        register_test_artifact_reference(
            image_id, conflicting_lineage, request, db_session
        )

    assert exc.value.status_code == 409
    assert db_session.query(models.ShelfImageArtifactReference).count() == 3

