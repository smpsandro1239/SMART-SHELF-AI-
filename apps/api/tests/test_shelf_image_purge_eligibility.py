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
