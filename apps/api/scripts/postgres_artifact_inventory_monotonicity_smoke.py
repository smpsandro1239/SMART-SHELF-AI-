"""Verify database-level monotonicity for signed artifact inventory snapshots."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app import models
from app.database import SessionLocal


def snapshot(*, image_id: int, store_id: int, actor_id: int, suffix: str, generated_at, source: str = "pg-monotonicity-smoke", manifest=None, artifact_count: int = 0, present_count: int = 0, absent_count: int = 0):
    return models.ShelfImageArtifactInventorySnapshot(
        shelf_image_id=image_id,
        store_id=store_id,
        external_system=source,
        snapshot_id=f"{suffix}-{uuid4().hex[:8]}",
        generated_at=generated_at,
        inventory_complete=True,
        manifest_sha256="a" * 64,
        source_signature="b" * 64,
        inventory_manifest=manifest if manifest is not None else [],
        artifact_count=artifact_count,
        present_count=present_count,
        absent_count=absent_count,
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

        # The database must also reject snapshots that are not strictly newer
        # than disposition history, even when no earlier snapshot exists.
        disposition_source = "pg-disposition-order-smoke"
        reference = models.ShelfImageArtifactReference(
            shelf_image_id=image_id,
            store_id=store_id,
            artifact_type="BACKUP",
            external_system=disposition_source,
            external_reference=f"backup/{suffix}",
            declared_by_user_id=actor_id,
        )
        db.add(reference)
        db.flush()
        disposition_at = accepted_at + timedelta(seconds=10)
        db.add(models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=reference.id,
            sequence_number=1,
            shelf_image_id=image_id,
            store_id=store_id,
            event_type="PROPOSED",
            actor_user_id=actor_id,
            reason="Verify snapshot/disposition chronology trigger",
            created_at=disposition_at,
        ))
        db.commit()

        # Direct SQLAlchemy inserts must not bypass manifest/reference integrity.
        valid_identity = {
            "artifact_type": "BACKUP",
            "external_reference": reference.external_reference,
            "sha256": None,
        }
        for label, manifest, present_count, absent_count in (
            (
                "wrong-reference",
                [{**valid_identity, "external_reference": "backup/not-the-declared-object", "state": "PRESENT"}],
                1,
                0,
            ),
            (
                "absent-without-attestation",
                [{**valid_identity, "state": "ABSENT"}],
                0,
                1,
            ),
        ):
            try:
                db.add(snapshot(
                    image_id=image_id,
                    store_id=store_id,
                    actor_id=actor_id,
                    suffix=f"manifest-{label}",
                    generated_at=disposition_at + timedelta(seconds=20),
                    source=disposition_source,
                    manifest=manifest,
                    artifact_count=1,
                    present_count=present_count,
                    absent_count=absent_count,
                ))
                db.commit()
            except IntegrityError:
                db.rollback()
            else:
                db.rollback()
                raise AssertionError(
                    f"PostgreSQL accepted an invalid direct inventory manifest: {label}"
                )

        try:
            db.add(snapshot(
                image_id=image_id,
                store_id=store_id,
                actor_id=actor_id,
                suffix="manifest-counter-mismatch",
                generated_at=disposition_at + timedelta(seconds=21),
                source=disposition_source,
                manifest=[{**valid_identity, "state": "PRESENT"}],
                artifact_count=1,
                present_count=0,
                absent_count=0,
            ))
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            db.rollback()
            raise AssertionError("PostgreSQL accepted inconsistent artifact inventory counters")

        for label, generated_at in (
            ("equal-to-disposition", disposition_at),
            ("older-than-disposition", disposition_at - timedelta(seconds=1)),
        ):
            try:
                db.add(snapshot(
                    image_id=image_id, store_id=store_id, actor_id=actor_id,
                    suffix=label, generated_at=generated_at,
                    source=disposition_source,
                ))
                db.commit()
            except IntegrityError:
                db.rollback()
            else:
                db.rollback()
                raise AssertionError(
                    f"PostgreSQL accepted a snapshot {label} for artifact disposition history"
                )

    print(
        "PostgreSQL artifact inventory integrity smoke passed: temporal ordering, exact reference coverage, manifest counters, and disposal-attested absence are enforced."
    )


if __name__ == "__main__":
    main()
