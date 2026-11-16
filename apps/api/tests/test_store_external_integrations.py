from datetime import timedelta
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app import models
from app.database import Base
from app.schemas import (
    ShelfImageArtifactInventorySnapshotCreate,
    StoreExternalIntegrationCreate,
    StoreExternalIntegrationUpdate,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def build_store_image(db):
    store = models.Store(code="INTEGRATION-STORE", name="Integration test store")
    db.add(store)
    db.flush()
    admin = models.User(
        email="integration-admin@example.test",
        full_name="Integration admin",
        password_hash="test-only",
        role="ADMIN",
        is_active=True,
    )
    db.add(admin)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Test zone")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="INTEGRATION-SHELF")
    db.add(shelf)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="integration.jpg",
        storage_path=f"/tmp/{store.id}/integration.jpg",
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256="a" * 64,
        analysis_status="COMPLETED",
        retention_status="RESTRICTED",
    )
    db.add(image)
    db.commit()
    return store.id, image.id, admin.id


def test_store_integration_registry_and_required_coverage(db_session):
    store_id, _, admin_id = build_store_image(db_session)
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    payload = StoreExternalIntegrationCreate(
        external_system="backup-vault",
        provider="s3-compatible",
        required_for_retention=True,
        capabilities=["inventory", "delete-attestation"],
    )

    record = main_module.create_store_external_integration(
        store_id, payload, request, db_session
    )
    assert record.status == "ACTIVE"
    assert record.last_seen_at is None
    assert record.capabilities == ["inventory", "delete-attestation"]

    listed = main_module.list_store_external_integrations(
        store_id, request, db_session
    )
    assert [item.external_system for item in listed] == ["backup-vault"]

    coverage = main_module.get_store_external_integration_coverage(
        store_id, request, db_session
    )
    assert coverage.required_integrations == 1
    assert coverage.active_required_integrations == 1
    assert coverage.never_seen_integrations == ["backup-vault"]
    assert coverage.missing_or_revoked_integrations == []
    assert coverage.stale_integrations == []

    record.last_seen_at = models.utc_now() - timedelta(minutes=60)
    db_session.commit()
    coverage = main_module.get_store_external_integration_coverage(
        store_id, request, db_session
    )
    assert coverage.stale_integrations == ["backup-vault"]

    updated = main_module.update_store_external_integration(
        store_id,
        record.id,
        StoreExternalIntegrationUpdate(status="REVOKED"),
        request,
        db_session,
    )
    assert updated.status == "REVOKED"
    coverage = main_module.get_store_external_integration_coverage(
        store_id, request, db_session
    )
    assert coverage.missing_or_revoked_integrations == ["backup-vault"]
    assert coverage.active_required_integrations == 0


def test_registry_is_store_scoped_and_duplicate_system_is_rejected(db_session):
    from fastapi import HTTPException

    store_a, _, admin_id = build_store_image(db_session)
    store_b = models.Store(code="INTEGRATION-STORE-B", name="Second store")
    db_session.add(store_b)
    db_session.commit()
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    payload = StoreExternalIntegrationCreate(
        external_system="backup-vault",
        provider="s3-compatible",
        required_for_retention=True,
    )
    first = main_module.create_store_external_integration(
        store_a, payload, request, db_session
    )
    second = main_module.create_store_external_integration(
        store_b.id, payload, request, db_session
    )
    assert first.id != second.id
    assert first.store_id != second.store_id

    with pytest.raises(HTTPException) as exc:
        main_module.create_store_external_integration(
            store_a, payload, request, db_session
        )
    assert exc.value.status_code == 409


def test_signed_inventory_rejects_unregistered_or_revoked_store_source(db_session):
    store_id, image_id, admin_id = build_store_image(db_session)
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    empty_coverage = main_module.get_store_external_integration_coverage(
        store_id, request, db_session
    )
    assert empty_coverage.coverage_configured is False
    assert empty_coverage.coverage_complete is False
    payload = ShelfImageArtifactInventorySnapshotCreate(
        external_system="backup-vault",
        snapshot_id="snapshot-unregistered",
        generated_at=models.utc_now(),
        inventory_complete=True,
        entries=[{
            "artifact_type": "BACKUP",
            "external_reference": "backup/image-1",
            "state": "PRESENT",
        }],
        signature="b" * 64,
    )

    with pytest.raises(HTTPException) as missing:
        main_module.create_shelf_image_artifact_inventory_snapshot(
            image_id, payload, request, db_session
        )
    assert missing.value.status_code == 409
    assert "not registered" in missing.value.detail

    integration = main_module.create_store_external_integration(
        store_id,
        StoreExternalIntegrationCreate(
            external_system="backup-vault",
            provider="s3-compatible",
            required_for_retention=True,
        ),
        request,
        db_session,
    )
    main_module.update_store_external_integration(
        store_id,
        integration.id,
        StoreExternalIntegrationUpdate(status="REVOKED"),
        request,
        db_session,
    )

    with pytest.raises(HTTPException) as revoked:
        main_module.create_shelf_image_artifact_inventory_snapshot(
            image_id, payload, request, db_session
        )
    assert revoked.value.status_code == 409
    assert "revoked" in revoked.value.detail
    assert db_session.query(models.ShelfImageArtifactInventorySnapshot).count() == 0


def test_integration_management_requires_admin(db_session):
    store_id, _, admin_id = build_store_image(db_session)
    employee = models.User(
        email="integration-employee@example.test",
        full_name="Employee",
        password_hash="test-only",
        role="EMPLOYEE",
        store_id=store_id,
        is_active=True,
    )
    db_session.add(employee)
    db_session.commit()
    request = SimpleNamespace(state=SimpleNamespace(user_id=employee.id))

    with pytest.raises(HTTPException) as exc:
        main_module.create_store_external_integration(
            store_id,
            StoreExternalIntegrationCreate(
                external_system="backup-vault",
                provider="s3-compatible",
            ),
            request,
            db_session,
        )
    assert exc.value.status_code == 403



def test_accepted_signed_snapshot_updates_integration_last_seen(db_session, monkeypatch):
    from app.artifact_inventory_signing import inventory_signature

    store_id, image_id, admin_id = build_store_image(db_session)
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))
    secret = "integration-test-secret-with-at-least-32-bytes"
    monkeypatch.setattr(
        main_module.settings,
        "artifact_inventory_hmac_keys_json",
        json.dumps({"backup-vault": secret}),
    )
    integration = main_module.create_store_external_integration(
        store_id,
        StoreExternalIntegrationCreate(
            external_system="backup-vault",
            provider="s3-compatible",
            required_for_retention=True,
        ),
        request,
        db_session,
    )
    db_session.add(models.ShelfImageArtifactReference(
        shelf_image_id=image_id,
        store_id=store_id,
        artifact_type="BACKUP",
        external_system="backup-vault",
        external_reference="backup/image-1",
        sha256=None,
        declared_by_user_id=admin_id,
    ))
    db_session.commit()

    generated_at = models.utc_now()
    entries = [{
        "artifact_type": "BACKUP",
        "external_reference": "backup/image-1",
        "sha256": None,
        "state": "PRESENT",
    }]
    signature = inventory_signature(
        image_id=image_id,
        store_id=store_id,
        external_system="backup-vault",
        snapshot_id="snapshot-accepted",
        generated_at=generated_at,
        entries=entries,
        secret=secret,
        inventory_complete=True,
    )
    payload = ShelfImageArtifactInventorySnapshotCreate(
        external_system="backup-vault",
        snapshot_id="snapshot-accepted",
        generated_at=generated_at,
        inventory_complete=True,
        entries=entries,
        signature=signature,
    )

    snapshot = main_module.create_shelf_image_artifact_inventory_snapshot(
        image_id, payload, request, db_session
    )

    db_session.refresh(integration)
    assert snapshot.store_id == store_id
    assert integration.last_seen_at is not None
    assert integration.last_seen_at.replace(tzinfo=generated_at.tzinfo) == generated_at

    older_generated_at = generated_at - timedelta(seconds=1)
    older_signature = inventory_signature(
        image_id=image_id,
        store_id=store_id,
        external_system="backup-vault",
        snapshot_id="snapshot-out-of-order",
        generated_at=older_generated_at,
        entries=entries,
        secret=secret,
        inventory_complete=True,
    )
    older_payload = ShelfImageArtifactInventorySnapshotCreate(
        external_system="backup-vault",
        snapshot_id="snapshot-out-of-order",
        generated_at=older_generated_at,
        inventory_complete=True,
        entries=entries,
        signature=older_signature,
    )
    with pytest.raises(HTTPException) as out_of_order:
        main_module.create_shelf_image_artifact_inventory_snapshot(
            image_id, older_payload, request, db_session
        )

    assert out_of_order.value.status_code == 409
    assert "newer than the latest accepted snapshot" in out_of_order.value.detail
    db_session.refresh(integration)
    assert integration.last_seen_at.replace(tzinfo=generated_at.tzinfo) == generated_at
    assert db_session.query(models.ShelfImageArtifactInventorySnapshot).count() == 1


def test_integration_update_rejects_explicit_null_values():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StoreExternalIntegrationUpdate(status=None)
    with pytest.raises(ValidationError):
        StoreExternalIntegrationUpdate(required_for_retention=None)
    with pytest.raises(ValidationError):
        StoreExternalIntegrationUpdate(capabilities=None)



def test_disposition_database_conflict_rolls_back_and_returns_conflict(db_session, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from app.schemas import ShelfImageArtifactDispositionActionRequest

    store_id, image_id, admin_id = build_store_image(db_session)
    artifact = models.ShelfImageArtifactReference(
        shelf_image_id=image_id,
        store_id=store_id,
        artifact_type="BACKUP",
        external_system="backup-vault",
        external_reference="backup/conflict-test",
        declared_by_user_id=admin_id,
    )
    db_session.add(artifact)
    db_session.commit()
    request = SimpleNamespace(state=SimpleNamespace(user_id=admin_id))

    original_rollback = db_session.rollback
    rollback_called = []
    def fail_commit():
        raise IntegrityError("INSERT disposition event", {}, Exception("unique conflict"))
    def tracked_rollback():
        rollback_called.append(True)
        original_rollback()

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", tracked_rollback)

    with pytest.raises(HTTPException) as conflict:
        main_module.create_shelf_image_artifact_disposition_event(
            image_id,
            artifact.id,
            ShelfImageArtifactDispositionActionRequest(
                action="PROPOSE",
                reason="Concurrent sequence conflict",
            ),
            request,
            db_session,
        )

    assert conflict.value.status_code == 409
    assert rollback_called == [True]
    assert db_session.query(models.ShelfImageArtifactDispositionEvent).count() == 0
