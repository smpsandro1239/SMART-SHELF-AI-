"""Verify append-only external artifact disposition history on PostgreSQL."""
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app import models
from app.database import SessionLocal


def main() -> None:
    suffix = uuid4().hex[:10]
    with SessionLocal() as db:
        store = models.Store(
            code=f"PG-ARTIFACT-DISPOSITION-{suffix}",
            name="Artifact disposition smoke store",
        )
        admin = models.User(
            email=f"pg-artifact-admin-{suffix}@example.test",
            full_name="Artifact disposition administrator",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        db.add_all([store, admin])
        db.flush()

        zone = models.Zone(store_id=store.id, name="Disposition smoke zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"ARTIFACT-{suffix}")
        db.add(shelf)
        db.flush()

        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="artifact-smoke.jpg",
            storage_path=f"/tmp/artifact-smoke-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="a" * 64,
            retention_status="RESTRICTED",
        )
        db.add(image)
        db.flush()

        artifact = models.ShelfImageArtifactReference(
            shelf_image_id=image.id,
            store_id=store.id,
            artifact_type="BACKUP",
            external_system="postgres-smoke",
            external_reference=f"backup/{suffix}",
            declared_by_user_id=admin.id,
        )
        db.add(artifact)
        db.flush()

        event = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=artifact.id,
            shelf_image_id=image.id,
            store_id=store.id,
            event_type="PROPOSED",
            actor_user_id=admin.id,
            reason="Verify PostgreSQL append-only trigger",
        )
        db.add(event)
        db.commit()
        event_id = event.id

    with SessionLocal() as db:
        event = db.get(models.ShelfImageArtifactDispositionEvent, event_id)
        assert event is not None
        event.reason = "Attempted mutation must fail"
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL allowed mutation of append-only disposition history")

    with SessionLocal() as db:
        event = db.get(models.ShelfImageArtifactDispositionEvent, event_id)
        assert event is not None
        db.delete(event)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL allowed deletion of append-only disposition history")

    print(
        "PostgreSQL artifact disposition smoke passed: "
        "disposition events reject UPDATE and DELETE."
    )


if __name__ == "__main__":
    main()
