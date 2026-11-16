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
        reviewer = models.User(
            email=f"pg-artifact-reviewer-{suffix}@example.test",
            full_name="Independent artifact reviewer",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        employee = models.User(
            email=f"pg-artifact-employee-{suffix}@example.test",
            full_name="Non-admin artifact operator",
            password_hash="smoke-test-only",
            role="EMPLOYEE",
            is_active=True,
        )
        db.add_all([store, admin, reviewer, employee])
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
        artifact_id = artifact.id
        image_id = image.id
        store_id = store.id
        admin_id = admin.id
        reviewer_id = reviewer.id
        employee_id = employee.id

    with SessionLocal() as db:
        invalid_self_approval = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=artifact_id,
            shelf_image_id=image_id,
            store_id=store_id,
            event_type="APPROVED",
            actor_user_id=admin_id,
            reason="Direct SQL self-approval must be rejected",
        )
        db.add(invalid_self_approval)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL accepted self-approval of an artifact disposition")

    with SessionLocal() as db:
        invalid_non_admin = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=artifact_id,
            shelf_image_id=image_id,
            store_id=store_id,
            event_type="APPROVED",
            actor_user_id=employee_id,
            reason="Non-admin approval must be rejected",
        )
        db.add(invalid_non_admin)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL accepted a disposition action by a non-admin")

    with SessionLocal() as db:
        independent_approval = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=artifact_id,
            shelf_image_id=image_id,
            store_id=store_id,
            event_type="APPROVED",
            actor_user_id=reviewer_id,
            reason="Independent administrator approval",
        )
        db.add(independent_approval)
        db.commit()
        approval_id = independent_approval.id

    with SessionLocal() as db:
        invalid_attestation = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=artifact_id,
            shelf_image_id=image_id,
            store_id=store_id,
            event_type="DISPOSAL_ATTESTED",
            actor_user_id=reviewer_id,
            evidence_reference="ticket/smoke",
            evidence_sha256="not-a-sha256",
            reason="Invalid evidence digest must be rejected",
        )
        db.add(invalid_attestation)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL accepted an invalid disposition evidence SHA-256")

    with SessionLocal() as db:
        other_store = models.Store(
            code=f"PG-ARTIFACT-OTHER-{suffix}",
            name="Other store for lineage violation",
        )
        db.add(other_store)
        db.commit()
        other_store_id = other_store.id

    with SessionLocal() as db:
        mismatched_artifact = models.ShelfImageArtifactReference(
            shelf_image_id=image_id,
            store_id=other_store_id,
            artifact_type="OTHER",
            external_system="postgres-smoke",
            external_reference=f"mismatched-artifact/{suffix}",
            declared_by_user_id=admin_id,
        )
        db.add(mismatched_artifact)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL accepted an artifact reference with mismatched store lineage")

    with SessionLocal() as db:
        mismatched_event = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=artifact_id,
            shelf_image_id=image_id,
            store_id=other_store_id,
            event_type="PROPOSED",
            actor_user_id=admin_id,
            reason="This mismatched store lineage must be rejected",
        )
        db.add(mismatched_event)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL accepted an artifact disposition with mismatched store lineage")

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
        "artifact references and events reject cross-store lineage; event triggers reject self-approval, non-admin actions and invalid evidence; event history rejects UPDATE and DELETE."
    )


if __name__ == "__main__":
    main()
