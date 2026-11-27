"""Prove PostgreSQL atomicity, concurrency, fencing and ACK immutability."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import models
from app.database import SessionLocal
from app.edge_event_processing import (
    EdgeEventProcessingError,
    claim_next_edge_event,
    complete_edge_event_transactionally,
)
from app.edge_event_worker import EdgeEventHandlerError
from app.edge_task_acknowledgement_service import apply_edge_task_acknowledgement
from app.edge_task_assignment_service import create_edge_task_assignment


def _expect_database_rejection(statement: str, acknowledgement_id: int) -> None:
    db = SessionLocal()
    try:
        try:
            db.execute(text(statement), {"ack_id": acknowledgement_id})
            db.commit()
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError(f"PostgreSQL trigger allowed forbidden SQL: {statement}")
    finally:
        db.close()


def main() -> None:
    suffix = uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        store = models.Store(code=f"EDGE-ACK-{suffix}", name="Edge ACK smoke")
        db.add(store)
        db.flush()
        user = models.User(
            email=f"edge-ack-{suffix}@example.test",
            store_id=store.id,
            full_name="CI Supervisor",
            password_hash="not-used-in-smoke",
            role="SUPERVISOR",
            is_active=True,
        )
        zone = models.Zone(store_id=store.id, name="Edge ACK zone")
        product = models.Product(sku=f"EDGE-ACK-SKU-{suffix}", name="Edge ACK product")
        device = models.EdgeDevice(
            device_id=f"edge-ack-device-{suffix}",
            store_id=store.id,
            device_type="robot",
            status="ACTIVE",
        )
        db.add_all([user, zone, product, device])
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"EDGE-ACK-SHELF-{suffix}")
        db.add(shelf)
        db.flush()
        task = models.ReplenishmentTask(
            store_id=store.id,
            shelf_id=shelf.id,
            product_id=product.id,
            status="PENDING",
            priority="NORMAL",
        )
        db.add(task)
        db.commit()

        store_id, task_id, device_id = store.id, task.id, device.device_id
        actor = SimpleNamespace(
            id=user.id, role=user.role, store_id=user.store_id, is_active=True,
        )
        assignment = create_edge_task_assignment(
            db,
            store_id=store_id,
            task_id=task_id,
            device_id=device_id,
            actor=actor,
            reason="Associação para smoke de ACK",
            valid_from=now - timedelta(minutes=2),
            valid_until=now + timedelta(hours=1),
        )
        assignment_id = assignment.id
        task_version = task.task_version

        inbox_rows = []
        for sequence, action in ((1, "COMPLETED"), (2, "ACCEPTED")):
            event_id = str(uuid4())
            occurred_at = now - timedelta(seconds=1)
            fingerprint = (f"{sequence:064x}")[-64:]
            inbox = models.EdgeDeviceEventInbox(
                device_id=device_id,
                event_id=event_id,
                sequence_number=sequence,
                event_type="TASK_ACKNOWLEDGED",
                store_id=store_id,
                shelf_id=None,
                occurred_at=occurred_at,
                payload={
                    "task_id": task_id,
                    "task_version": task_version,
                    "action": action,
                },
                fingerprint_sha256=fingerprint,
                received_at=now - timedelta(seconds=1),
            )
            inbox_rows.append(inbox)
        db.add_all(inbox_rows)
        db.flush()
        processing_rows = [
            models.EdgeDeviceEventProcessing(
                inbox_id=row.id,
                status="PENDING",
                attempt_count=0,
                max_attempts=8,
                available_at=now - timedelta(seconds=1),
                fencing_token=0,
                created_at=now,
                updated_at=now,
            )
            for row in inbox_rows
        ]
        db.add_all(processing_rows)
        db.commit()
        inbox_ids = [row.id for row in inbox_rows]
    finally:
        db.close()

    # 1. Claim the COMPLETED declaration and force a failure after the ACK
    # insert. Both the ACK and the PROCESSED transition must roll back.
    with SessionLocal() as claim_db:
        first_claim = claim_next_edge_event(
            claim_db, worker_id=f"ack-smoke-{suffix}-old", lease_seconds=5, now=now,
        )
    assert first_claim is not None and first_claim["inbox_id"] == inbox_ids[0]

    def fail_after_ack(session, event):
        apply_edge_task_acknowledgement(session, event)
        raise RuntimeError("intentional rollback probe")

    try:
        with SessionLocal() as tx:
            complete_edge_event_transactionally(
                tx,
                processing_id=first_claim["processing_id"],
                worker_id=f"ack-smoke-{suffix}-old",
                fencing_token=first_claim["fencing_token"],
                event=first_claim,
                handler=fail_after_ack,
                now=now + timedelta(seconds=1),
            )
    except RuntimeError as exc:
        assert str(exc) == "intentional rollback probe"
    else:
        raise AssertionError("transactional handler failure did not propagate")

    with SessionLocal() as verify:
        assert verify.query(models.EdgeTaskAcknowledgement).filter_by(
            inbox_id=inbox_ids[0]
        ).count() == 0
        processing = verify.query(models.EdgeDeviceEventProcessing).filter_by(
            inbox_id=inbox_ids[0]
        ).one()
        assert processing.status == "PROCESSING"
        assert processing.lease_owner == f"ack-smoke-{suffix}-old"

    # 2. Reclaim after expiry; fencing must increase and the stale worker
    # must not be able to commit, even if it still has the original payload.
    reclaim_at = first_claim["lease_expires_at"] + timedelta(seconds=1)
    with SessionLocal() as claim_db:
        current_claim = claim_next_edge_event(
            claim_db,
            worker_id=f"ack-smoke-{suffix}-new",
            lease_seconds=30,
            now=reclaim_at,
        )
    assert current_claim is not None
    assert current_claim["inbox_id"] == inbox_ids[0]
    assert current_claim["fencing_token"] > first_claim["fencing_token"]

    try:
        with SessionLocal() as stale_db:
            complete_edge_event_transactionally(
                stale_db,
                processing_id=first_claim["processing_id"],
                worker_id=f"ack-smoke-{suffix}-old",
                fencing_token=first_claim["fencing_token"],
                event=first_claim,
                handler=apply_edge_task_acknowledgement,
                now=reclaim_at + timedelta(seconds=1),
            )
    except EdgeEventProcessingError:
        pass
    else:
        raise AssertionError("stale fenced worker unexpectedly committed")

    with SessionLocal() as tx:
        complete_edge_event_transactionally(
            tx,
            processing_id=current_claim["processing_id"],
            worker_id=f"ack-smoke-{suffix}-new",
            fencing_token=current_claim["fencing_token"],
            event=current_claim,
            handler=apply_edge_task_acknowledgement,
        )

    # 3. Exact replay cannot create a second ledger row.
    try:
        with SessionLocal() as duplicate_db:
            apply_edge_task_acknowledgement(duplicate_db, current_claim)
            duplicate_db.commit()
    except EdgeEventHandlerError as exc:
        assert exc.code == "DUPLICATE_ACK_EVENT"
    else:
        raise AssertionError("duplicate ACK replay was accepted")

    # 4. Two workers racing for the remaining inbox item must yield one claim.
    barrier = Barrier(2)
    concurrent_now = datetime.now(timezone.utc)

    def race_claim(worker_suffix: str):
        with SessionLocal() as worker_db:
            barrier.wait(timeout=10)
            return claim_next_edge_event(
                worker_db,
                worker_id=f"ack-smoke-{suffix}-{worker_suffix}",
                lease_seconds=30,
                now=concurrent_now,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(race_claim, ("race-a", "race-b")))
    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1, f"expected exactly one concurrent claim, got {len(winners)}"
    second_claim = winners[0]
    assert second_claim["inbox_id"] == inbox_ids[1]

    with SessionLocal() as tx:
        complete_edge_event_transactionally(
            tx,
            processing_id=second_claim["processing_id"],
            worker_id=next(
                worker for worker in (f"ack-smoke-{suffix}-race-a", f"ack-smoke-{suffix}-race-b")
                if worker == second_claim.get("worker_id", worker)
            ) if False else (
                f"ack-smoke-{suffix}-race-a"
                if second_claim["fencing_token"] == 1
                else f"ack-smoke-{suffix}-race-b"
            ),
            fencing_token=second_claim["fencing_token"],
            event=second_claim,
            handler=apply_edge_task_acknowledgement,
        )

    # 5. PostgreSQL triggers, not Python-only guards, enforce append-only.
    with SessionLocal() as verify:
        acknowledgements = (
            verify.query(models.EdgeTaskAcknowledgement)
            .order_by(models.EdgeTaskAcknowledgement.id)
            .all()
        )
        assert len(acknowledgements) == 2
        completed = next(row for row in acknowledgements if row.action == "COMPLETED")
        accepted = next(row for row in acknowledgements if row.action == "ACCEPTED")
        assert completed.result == "REVIEW_REQUIRED"
        assert accepted.result == "ACCEPTED"
        assert completed.fingerprint_sha256 == inbox_rows[0].fingerprint_sha256
        task_after = verify.get(models.ReplenishmentTask, task_id)
        assert task_after.status == "PENDING"
        assert task_after.task_version == task_version
        assert task_after.completed_at is None
        assert verify.query(models.InventoryMovement).count() == 0
        processing_states = {
            row.inbox_id: row.status
            for row in verify.query(models.EdgeDeviceEventProcessing)
            .filter(models.EdgeDeviceEventProcessing.inbox_id.in_(inbox_ids))
            .all()
        }
        assert processing_states == {inbox_ids[0]: "PROCESSED", inbox_ids[1]: "PROCESSED"}
        completed_ack_id = completed.id

    _expect_database_rejection(
        "UPDATE edge_task_acknowledgements SET result = 'ACCEPTED' WHERE id = :ack_id",
        completed_ack_id,
    )
    _expect_database_rejection(
        "DELETE FROM edge_task_acknowledgements WHERE id = :ack_id",
        completed_ack_id,
    )

    with SessionLocal() as verify:
        assert verify.query(models.EdgeTaskAcknowledgement).count() == 2

    print(
        "PostgreSQL Edge ACK smoke passed: atomic rollback/commit, replay rejection, "
        "single-winner concurrent claim, fencing, COMPLETED review-only semantics, "
        "no inventory side effects and database-enforced append-only triggers."
    )


if __name__ == "__main__":
    main()
