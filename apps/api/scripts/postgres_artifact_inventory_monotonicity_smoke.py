"""Verify database-level monotonicity for signed artifact inventory snapshots."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app import models
from app.database import SessionLocal


def snapshot(*, image_id: int, store_id: int, actor_id: int, suffix: str, generated_at, source: str = "pg-monotonicity-smoke"):
    return models.ShelfImageArtifactInventorySnapshot(
        shelf_image_id=image_id,
        store_id=store_id,
        external_system=source,
        snapshot_id=f"{suffix}-{uuid4().hex[:8]}",
        generated_at=generated_at,
        inventory_complete=True,
        manifest_sha256="a" * 64,
        source_signature="b" * 64,
        inventory_manifest=[],
        artifact_count=0,
        present_count=0,
        absent_count=0,
        verified_at=models.utc_now(),
        created_by_user_id=actor_id,
    )


def main() -> None:
    with SessionLocal() as db:
        suffix = uuid4().hex[:12]
        store = models.Store(code=f"PG-MONO-{suffix}", name="Snapshot monotonicity smoke")
        db.add(store)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Monotonicity zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"MONO-{suffix}")
        db.add(shelf)
        db.flush()
        actor = models.User(
            email=f"pg-mono-{suffix}@example.test",
            full_name="Snapshot monotonicity administrator",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        db.add(actor)
        db.flush()
        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="monotonicity.jpg",
            storage_path="/tmp/monotonicity.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="c" * 64,
            retention_status="RESTRICTED",
        )
        db.add(image)
        db.flush()

        accepted_at = models.utc_now()
        db.add(snapshot(
            image_id=image.id, store_id=store.id, actor_id=actor.id,
            suffix="accepted", generated_at=accepted_at,
        ))
        db.commit()
        image_id, store_id, actor_id = image.id, store.id, actor.id

        for label, generated_at in (
            ("older", accepted_at - timedelta(seconds=1)),
            ("equal", accepted_at),
        ):
            try:
                db.add(snapshot(
                    image_id=image_id, store_id=store_id, actor_id=actor_id,
                    suffix=label, generated_at=generated_at,
                ))
                db.commit()
            except IntegrityError:
                db.rollback()
            else:
                db.rollback()
                raise AssertionError(
                    f"PostgreSQL accepted {label} inventory snapshot for the same image/source"
                )

        # The monotonicity boundary is scoped to an external source.
        db.add(snapshot(
            image_id=image_id, store_id=store_id, actor_id=actor_id,
            suffix="other-source", generated_at=accepted_at,
            source="pg-monotonicity-other-source",
        ))
        db.commit()

    print(
        "PostgreSQL artifact inventory monotonicity smoke passed: older and "
        "equal timestamps are rejected, while independent sources remain isolated."
    )


if __name__ == "__main__":
    main()
