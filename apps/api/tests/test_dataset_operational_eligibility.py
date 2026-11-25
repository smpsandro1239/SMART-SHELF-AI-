import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.database import Base
from app.dataset_operational_eligibility import (
    _internal_image_lock_statement,
    validate_internal_image_eligibility,
)
from app import models


@pytest.fixture
def operational_db():
    engine = create_engine("sqlite:///:memory:")
    tables = [
        models.Store.__table__,
        models.Zone.__table__,
        models.Shelf.__table__,
        models.ShelfImage.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    db = Session(engine)
    store = models.Store(code="DATASET-STORE", name="Dataset Store")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="A")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="A-01")
    db.add(shelf)
    db.flush()
    digest = hashlib.sha256(b"internal-image").hexdigest()
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="shelf.jpg",
        storage_path="dataset-test/shelf.jpg",
        mime_type="image/jpeg",
        file_size_bytes=14,
        sha256=digest,
        retention_status="ACTIVE",
        legal_hold=False,
    )
    db.add(image)
    db.commit()
    yield db, store.id, image.id, digest
    db.close()
    engine.dispose()


def internal_entry(image_id, store_id, digest):
    return {
        "source_type": "internal",
        "shelf_image_id": image_id,
        "store_id": store_id,
        "source_image_sha256": digest,
    }


def test_internal_image_is_approved_when_store_hash_and_retention_match(operational_db):
    db, store_id, image_id, digest = operational_db
    errors, report = validate_internal_image_eligibility(
        db, [internal_entry(image_id, store_id, digest)]
    )
    assert errors == []
    assert report["status"] == "APPROVED"
    assert report["checked_images"] == 1
    assert report["locked_image_ids"] == [image_id]
    assert report["locked_shelf_ids"] == [db.query(models.Shelf.id).scalar()]
    assert report["locked_zone_ids"] == [db.query(models.Zone.id).scalar()]


def test_internal_image_requires_database_session(operational_db):
    _db, store_id, image_id, digest = operational_db
    errors, report = validate_internal_image_eligibility(
        None, [internal_entry(image_id, store_id, digest)]
    )
    assert report["status"] == "BLOCKED"
    assert any("database session is required" in error for error in errors)


def test_internal_image_cannot_claim_another_store(operational_db):
    db, store_id, image_id, digest = operational_db
    errors, _ = validate_internal_image_eligibility(
        db, [internal_entry(image_id, store_id + 100, digest)]
    )
    assert any("does not belong to declared store_id" in error for error in errors)


def test_internal_image_hash_must_match_operational_record(operational_db):
    db, store_id, image_id, _digest = operational_db
    errors, _ = validate_internal_image_eligibility(
        db, [internal_entry(image_id, store_id, "0" * 64)]
    )
    assert any("does not match operational shelf image" in error for error in errors)


@pytest.mark.parametrize("status", ["RESTRICTED", "PENDING_PURGE", "PURGED"])
def test_non_active_internal_image_is_blocked(operational_db, status):
    db, store_id, image_id, digest = operational_db
    image = db.get(models.ShelfImage, image_id)
    image.retention_status = status
    db.commit()
    errors, _ = validate_internal_image_eligibility(
        db, [internal_entry(image_id, store_id, digest)]
    )
    assert any("is not ACTIVE" in error for error in errors)


def test_internal_image_under_legal_hold_is_blocked(operational_db):
    db, store_id, image_id, digest = operational_db
    image = db.get(models.ShelfImage, image_id)
    image.legal_hold = True
    db.commit()
    errors, _ = validate_internal_image_eligibility(
        db, [internal_entry(image_id, store_id, digest)]
    )
    assert any("under legal hold" in error for error in errors)


def test_missing_internal_image_is_blocked(operational_db):
    db, store_id, image_id, digest = operational_db
    errors, _ = validate_internal_image_eligibility(
        db, [internal_entry(image_id + 999, store_id, digest)]
    )
    assert any("does not exist" in error for error in errors)


def test_external_only_provenance_does_not_require_database():
    errors, report = validate_internal_image_eligibility(
        None, [{"source_type": "external"}]
    )
    assert errors == []
    assert report["status"] == "APPROVED"
    assert report["internal_images"] == 0



def test_postgresql_eligibility_query_locks_image_shelf_and_zone_in_stable_order():
    statement = _internal_image_lock_statement([9, 2])
    sql = str(statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))

    assert "FOR UPDATE OF shelf_images, shelves, zones" in sql
    assert "ORDER BY shelf_images.id ASC, shelves.id ASC, zones.id ASC" in sql
    assert "shelf_images.id IN (9, 2)" in sql


def test_eligibility_report_is_empty_for_external_only_sources():
    errors, report = validate_internal_image_eligibility(
        None,
        [{"source_type": "external", "source_name": "licensed-source"}],
    )

    assert errors == []
    assert report["status"] == "APPROVED"
    assert report["internal_images"] == 0
    assert report["locked_image_ids"] == []
    assert report["locked_shelf_ids"] == []
    assert report["locked_zone_ids"] == []
