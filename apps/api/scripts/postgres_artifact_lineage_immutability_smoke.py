"""Verify recorded external artifacts prevent later cross-store lineage changes."""

from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app import models
from app.database import SessionLocal


def expect_rejected(db, statement, description: str) -> None:
    try:
        statement()
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        db.rollback()
        raise AssertionError(f"PostgreSQL accepted forbidden lineage mutation: {description}")


def main() -> None:
    with SessionLocal() as db:
        suffix = uuid4().hex[:12]
        store_a = models.Store(code=f"PG-LINEAGE-A-{suffix}", name="Lineage store A")
        store_b = models.Store(code=f"PG-LINEAGE-B-{suffix}", name="Lineage store B")
        db.add_all([store_a, store_b])
        db.flush()

        zone_a = models.Zone(store_id=store_a.id, name="Lineage zone A")
        zone_b = models.Zone(store_id=store_b.id, name="Lineage zone B")
        db.add_all([zone_a, zone_b])
        db.flush()

        shelf_a = models.Shelf(zone_id=zone_a.id, code=f"LINEAGE-A-{suffix}")
        shelf_b = models.Shelf(zone_id=zone_b.id, code=f"LINEAGE-B-{suffix}")
        db.add_all([shelf_a, shelf_b])
        db.flush()

        actor = models.User(
            email=f"pg-lineage-{suffix}@example.test",
            full_name="Lineage smoke administrator",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        db.add(actor)
        db.flush()

        image = models.ShelfImage(
            shelf_id=shelf_a.id,
            original_filename="lineage-smoke.jpg",
            storage_path="/tmp/lineage-smoke.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="c" * 64,
            retention_status="RESTRICTED",
        )
        db.add(image)
        db.flush()

        artifact = models.ShelfImageArtifactReference(
            shelf_image_id=image.id,
            store_id=store_a.id,
            artifact_type="BACKUP",
            external_system="postgres-lineage-smoke",
            external_reference=f"backup/{image.id}",
            declared_by_user_id=actor.id,
        )
        db.add(artifact)
        db.commit()

        image_id = image.id
        shelf_a_id, shelf_b_id = shelf_a.id, shelf_b.id
        zone_a_id, zone_b_id = zone_a.id, zone_b.id
        store_b_id = store_b.id

    with SessionLocal() as db:
        expect_rejected(
            db,
            lambda: db.query(models.ShelfImage)
            .filter(models.ShelfImage.id == image_id)
            .update({models.ShelfImage.shelf_id: shelf_b_id}),
            "moving an image to another shelf",
        )
        expect_rejected(
            db,
            lambda: db.query(models.Shelf)
            .filter(models.Shelf.id == shelf_a_id)
            .update({models.Shelf.zone_id: zone_b_id}),
            "moving a shelf to another zone",
        )
        expect_rejected(
            db,
            lambda: db.query(models.Zone)
            .filter(models.Zone.id == zone_a_id)
            .update({models.Zone.store_id: store_b_id}),
            "moving a zone to another store",
        )

    print(
        "PostgreSQL artifact lineage smoke passed: image shelf, shelf zone, "
        "and zone store mutations are rejected after artifact registration."
    )


if __name__ == "__main__":
    main()
