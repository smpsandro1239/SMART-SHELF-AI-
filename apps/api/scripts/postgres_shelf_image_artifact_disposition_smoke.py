"""Verify append-only external artifact disposition history on PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import sleep
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
        attestor = models.User(
            email=f"pg-artifact-attestor-{suffix}@example.test",
            full_name="Independent artifact attestor",
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
        db.add_all([store, admin, reviewer, attestor, employee])
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
            sequence_number=1,
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
        attestor_id = attestor.id
        employee_id = employee.id

    with SessionLocal() as db:
        concurrent_artifact = models.ShelfImageArtifactReference(
            shelf_image_id=image_id,
            store_id=store_id,
            artifact_type="CACHE",
            external_system="postgres-smoke",
            external_reference=f"concurrent/{suffix}",
            declared_by_user_id=admin_id,
        )
        serialized_artifact = models.ShelfImageArtifactReference(
            shelf_image_id=image_id,
            store_id=store_id,
            artifact_type="OTHER",
            external_system="postgres-smoke",
            external_reference=f"image-lock/{suffix}",
            declared_by_user_id=admin_id,
        )
        db.add_all([concurrent_artifact, serialized_artifact])
        db.commit()
        concurrent_artifact_id = concurrent_artifact.id
        serialized_artifact_id = serialized_artifact.id

    # A direct SQLAlchemy insert must acquire the image lock before the
    # existing validation trigger locks the artifact-reference row.
    insert_started = Event()

    def insert_disposition_while_image_is_locked() -> str:
        with SessionLocal() as db:
            candidate = models.ShelfImageArtifactDispositionEvent(
                artifact_reference_id=serialized_artifact_id,
                sequence_number=1,
                shelf_image_id=image_id,
                store_id=store_id,
                event_type="PROPOSED",
                actor_user_id=admin_id,
                reason="Verify image-first database lock order",
            )
            db.add(candidate)
            insert_started.set()
            db.commit()
            return "committed"

    with SessionLocal() as image_lock_db:
        image_lock_db.query(models.ShelfImage).filter(
            models.ShelfImage.id == image_id
        ).with_for_update().one()
        with ThreadPoolExecutor(max_workers=1) as executor:
            blocked_insert = executor.submit(insert_disposition_while_image_is_locked)
            assert insert_started.wait(timeout=5), "Disposition insert did not start"
            sleep(0.25)
            assert not blocked_insert.done(), (
                "Direct disposition insert did not wait for the source image lock"
            )
            image_lock_db.commit()
            assert blocked_insert.result(timeout=5) == "committed"

    barrier = Barrier(2)

    def propose_concurrently(actor_id: int) -> str:
        with SessionLocal() as db:
            candidate = models.ShelfImageArtifactDispositionEvent(
                artifact_reference_id=concurrent_artifact_id,
                sequence_number=1,
                shelf_image_id=image_id,
                store_id=store_id,
                event_type="PROPOSED",
                actor_user_id=actor_id,
                reason="Concurrent proposal serialization check",
            )
            db.add(candidate)
            barrier.wait(timeout=10)
            try:
                db.commit()
                return "committed"
            except IntegrityError:
                db.rollback()
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(propose_concurrently, [admin_id, reviewer_id]))
    assert outcomes.count("committed") == 1, outcomes
    assert outcomes.count("rejected") == 1, outcomes

    with SessionLocal() as db:
        concurrent_events = (
            db.query(models.ShelfImageArtifactDispositionEvent)
            .filter(
                models.ShelfImageArtifactDispositionEvent.artifact_reference_id
                == concurrent_artifact_id
            )
            .all()
        )
        assert len(concurrent_events) == 1
        assert concurrent_events[0].sequence_number == 1

    with SessionLocal() as db:
        unproposed_artifact = models.ShelfImageArtifactReference(
            shelf_image_id=image_id,
            store_id=store_id,
            artifact_type="REPORT",
            external_system="postgres-smoke",
            external_reference=f"unproposed/{suffix}",
            declared_by_user_id=admin_id,
        )
        db.add(unproposed_artifact)
        db.commit()
        unproposed_artifact_id = unproposed_artifact.id

    with SessionLocal() as db:
        approval_without_proposal = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=unproposed_artifact_id,
            sequence_number=1,
            shelf_image_id=image_id,
            store_id=store_id,
            event_type="APPROVED",
            actor_user_id=reviewer_id,
            reason="An approval without a proposal must be rejected",
        )
        db.add(approval_without_proposal)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL accepted approval without a proposal")

    with SessionLocal() as db:
        invalid_self_approval = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=artifact_id,
            sequence_number=2,
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
            sequence_number=2,
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
            sequence_number=2,
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
            sequence_number=3,
            shelf_image_id=image_id,
            store_id=store_id,
            event_type="DISPOSAL_ATTESTED",
            actor_user_id=attestor_id,
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
        valid_attestation = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=artifact_id,
            sequence_number=3,
            shelf_image_id=image_id,
            store_id=store_id,
            event_type="DISPOSAL_ATTESTED",
            actor_user_id=attestor_id,
            evidence_reference="ticket/smoke",
            evidence_sha256="b" * 64,
            reason="Independent attestation with valid evidence digest",
        )
        db.add(valid_attestation)
        db.commit()

    with SessionLocal() as db:
        invalid_sequence = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=artifact_id,
            sequence_number=5,
            shelf_image_id=image_id,
            store_id=store_id,
            event_type="PROPOSED",
            actor_user_id=admin_id,
            reason="Sequence gaps must be rejected",
        )
        db.add(invalid_sequence)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL accepted a non-contiguous disposition sequence")

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
            sequence_number=4,
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
        mismatched_image_event = models.ShelfImageArtifactDispositionEvent(
            artifact_reference_id=artifact_id,
            sequence_number=4,
            shelf_image_id=image_id + 999999,
            store_id=store_id,
            event_type="PROPOSED",
            actor_user_id=admin_id,
            reason="A mismatched image identifier must be rejected before locking",
        )
        db.add(mismatched_image_event)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL accepted a disposition event with mismatched image lineage")

    with SessionLocal() as db:
        actor = db.get(models.User, admin_id)
        assert actor is not None
        db.delete(actor)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL allowed deletion of an administrator referenced by immutable audit history")

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
        "artifact references and events reject cross-store lineage; concurrent proposals serialize to one event; event triggers acquire the source-image lock before artifact locks, reject self-approval, non-admin actions, invalid evidence and non-contiguous sequences; event history rejects actor deletion, UPDATE and DELETE."
    )


if __name__ == "__main__":
    main()
