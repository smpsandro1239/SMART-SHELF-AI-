"""Prove PostgreSQL atomicity, concurrency, fencing and ACK immutability."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Thread
import time
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
from app.edge_task_assignment_service import (
    create_edge_task_assignment,
    revoke_edge_task_assignment,
)


def _expect_database_rejection(statement: str, acknowledgement_id: int) -> None:
    db = SessionLocal()
    try:
        try:
            db.execute(text(statement), {"ack_id": acknowledgement_id})
            db.commit()
        except DBAPIError as exc:
            db.rollback()
            assert "append-only" in str(exc.orig), str(exc.orig)
        else:
            raise AssertionError(f"PostgreSQL trigger allowed forbidden SQL: {statement}")
    finally:
        db.close()


def _set_application_name(db, name: str) -> int:
    db.execute(text("SELECT set_config('application_name', :name, false)"), {"name": name})
    return db.execute(text("SELECT pg_backend_pid()")).scalar_one()


def _wait_for_postgres_lock(application_name: str, blocker_pid: int) -> None:
    """Require PostgreSQL itself to report the waiter and its actual blocker."""
    deadline = time.monotonic() + 15
    last_state = None
    while time.monotonic() < deadline:
        with SessionLocal() as observer:
            row = observer.execute(text("""
                SELECT pid, wait_event_type, wait_event, pg_blocking_pids(pid) AS blockers
                FROM pg_stat_activity
                WHERE application_name = :application_name
            """), {"application_name": application_name}).mappings().first()
        if row is not None:
            last_state = dict(row)
            if row["wait_event_type"] == "Lock" and blocker_pid in row["blockers"]:
                return
        time.sleep(0.05)
    raise AssertionError(
        f"PostgreSQL did not report the expected lock wait for {application_name}; "
        f"last state={last_state!r}, blocker_pid={blocker_pid}"
    )


def _create_race_assignment_and_claim(
    *, suffix: str, scenario: str, store_id: int, task_id: int, device_id: str,
    actor, task_version: int,
) -> tuple[int, dict]:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        assignment = create_edge_task_assignment(
            db, store_id=store_id, task_id=task_id, device_id=device_id,
            actor=actor, reason=f"ACK race {scenario}",
            valid_from=now - timedelta(minutes=5),
            valid_until=now + timedelta(hours=1),
        )
        inbox = models.EdgeDeviceEventInbox(
            device_id=device_id, event_id=str(uuid4()), sequence_number=100 + (1 if scenario == "A" else 2),
            event_type="TASK_ACKNOWLEDGED", store_id=store_id, shelf_id=None,
            occurred_at=now - timedelta(seconds=1),
            payload={"task_id": task_id, "task_version": task_version, "action": "ACCEPTED"},
            fingerprint_sha256=(uuid4().hex * 2)[:64],
            received_at=now - timedelta(seconds=1),
        )
        db.add(inbox)
        db.flush()
        inbox_id = inbox.id
        processing = models.EdgeDeviceEventProcessing(
            inbox_id=inbox_id, status="PENDING", attempt_count=0, max_attempts=8,
            available_at=now - timedelta(seconds=1), fencing_token=0,
            created_at=now, updated_at=now,
        )
        db.add(processing)
        db.commit()
    with SessionLocal() as claim_db:
        claim = claim_next_edge_event(
            claim_db, worker_id=f"ack-race-{suffix}-{scenario}",
            lease_seconds=120, now=now,
        )
    assert claim is not None and claim["inbox_id"] == inbox_id
    return assignment.id, claim


def _prove_revocation_ack_races(
    *, suffix: str, store_id: int, task_id: int, device_id: str,
    actor, task_version: int, original_assignment_id: int,
) -> None:
    # Free the original assignment so each race gets an independent, auditable
    # association and a distinct inbox event.
    with SessionLocal() as db:
        revoke_edge_task_assignment(
            db, assignment_id=original_assignment_id, actor=actor,
            reason="Preparar cenários concorrentes ACK",
        )

    # Scenario A: revocation owns Store -> Task -> Device -> Assignment first.
    assignment_a, claim_a = _create_race_assignment_and_claim(
        suffix=suffix, scenario="A", store_id=store_id, task_id=task_id,
        device_id=device_id, actor=actor, task_version=task_version,
    )
    revoke_tx = SessionLocal()
    blocker_pid = _set_application_name(revoke_tx, f"ack-race-{suffix}-revoke-a")
    revoke_tx.query(models.Store).filter_by(id=store_id).with_for_update().populate_existing().one()
    revoke_tx.query(models.ReplenishmentTask).filter_by(
        id=task_id, store_id=store_id
    ).with_for_update().populate_existing().one()
    revoke_tx.query(models.EdgeDevice).filter_by(
        device_id=device_id, store_id=store_id
    ).with_for_update().populate_existing().one()
    assignment_row = revoke_tx.query(models.EdgeDeviceTaskAssignment).filter_by(
        id=assignment_a, store_id=store_id
    ).with_for_update().populate_existing().one()
    revoked_at = models.utc_now()
    assignment_row.revoked_at = revoked_at
    assignment_row.revoked_by_user_id = actor.id
    assignment_row.revocation_reason = "Revogação vence corrida ACK"
    revoke_tx.add(models.EdgeDeviceTaskAssignmentEvent(
        assignment_id=assignment_a, event_type="REVOKED",
        actor_user_id=actor.id, reason="Revogação vence corrida ACK",
        details={"task_version": task_version}, created_at=revoked_at,
    ))
    revoke_tx.flush()

    started_a = Event()
    outcome_a = {}

    def process_after_revocation_lock():
        with SessionLocal() as worker_db:
            pid = _set_application_name(worker_db, f"ack-race-{suffix}-ack-a")
            outcome_a["pid"] = pid
            started_a.set()
            try:
                complete_edge_event_transactionally(
                    worker_db, processing_id=claim_a["processing_id"],
                    worker_id=f"ack-race-{suffix}-A",
                    fencing_token=claim_a["fencing_token"], event=claim_a,
                    handler=apply_edge_task_acknowledgement,
                )
            except EdgeEventHandlerError as exc:
                outcome_a["error"] = exc.code

    worker_a = Thread(target=process_after_revocation_lock, daemon=True)
    worker_a.start()
    assert started_a.wait(10), "ACK worker A did not start"
    _wait_for_postgres_lock(f"ack-race-{suffix}-ack-a", blocker_pid)
    revoke_tx.commit()
    revoke_tx.close()
    worker_a.join(15)
    assert not worker_a.is_alive(), "ACK worker A did not resume after revocation commit"
    assert outcome_a.get("error") == "UNASSIGNED_DEVICE", outcome_a
    with SessionLocal() as verify:
        assert verify.query(models.EdgeTaskAcknowledgement).filter_by(
            inbox_id=claim_a["inbox_id"]
        ).count() == 0
        assert verify.get(models.EdgeDeviceTaskAssignment, assignment_a).revoked_at is not None
        # The transactional handler rolls back atomically on rejection; the
        # worker retry/dead-letter policy is deliberately outside this smoke.
        assert verify.query(models.EdgeDeviceEventProcessing).filter_by(
            id=claim_a["processing_id"], status="PROCESSING"
        ).count() == 1

    # Scenario B: ACK owns the same canonical lock chain first. The revocation
    # service must wait on Store, then commit after the ACK transaction commits.
    assignment_b, claim_b = _create_race_assignment_and_claim(
        suffix=suffix, scenario="B", store_id=store_id, task_id=task_id,
        device_id=device_id, actor=actor, task_version=task_version,
    )
    ack_locks_acquired = Event()
    allow_ack_commit = Event()
    outcome_b = {}

    def hold_ack_after_domain_locks(session, event):
        apply_edge_task_acknowledgement(session, event)
        ack_locks_acquired.set()
        if not allow_ack_commit.wait(15):
            raise AssertionError("timed out waiting to release ACK transaction B")

    def process_ack_b():
        with SessionLocal() as worker_db:
            outcome_b["pid"] = _set_application_name(
                worker_db, f"ack-race-{suffix}-ack-b"
            )
            complete_edge_event_transactionally(
                worker_db, processing_id=claim_b["processing_id"],
                worker_id=f"ack-race-{suffix}-B",
                fencing_token=claim_b["fencing_token"], event=claim_b,
                handler=hold_ack_after_domain_locks,
            )
            outcome_b["committed"] = True

    worker_b = Thread(target=process_ack_b, daemon=True)
    worker_b.start()
    assert ack_locks_acquired.wait(10), "ACK B did not acquire domain locks"
    revoke_started_b = Event()
    revoke_outcome_b = {}

    def revoke_after_ack_lock():
        with SessionLocal() as revoke_db:
            _set_application_name(revoke_db, f"ack-race-{suffix}-revoke-b")
            revoke_started_b.set()
            try:
                revoke_edge_task_assignment(
                    revoke_db, assignment_id=assignment_b, actor=actor,
                    reason="Revogação aguarda ACK",
                )
                revoke_outcome_b["committed"] = True
            except Exception as exc:  # surfaced below with its exact type/message
                revoke_outcome_b["error"] = f"{type(exc).__name__}: {exc}"

    revoker_b = Thread(target=revoke_after_ack_lock, daemon=True)
    revoker_b.start()
    assert revoke_started_b.wait(10), "revocation B did not start"
    _wait_for_postgres_lock(f"ack-race-{suffix}-revoke-b", outcome_b["pid"])
    allow_ack_commit.set()
    worker_b.join(15)
    revoker_b.join(15)
    assert not worker_b.is_alive() and not revoker_b.is_alive(), (
        "scenario B transactions did not finish"
    )
    assert outcome_b.get("committed") is True, outcome_b
    assert revoke_outcome_b.get("committed") is True, revoke_outcome_b

    with SessionLocal() as verify:
        ack_b = verify.query(models.EdgeTaskAcknowledgement).filter_by(
            inbox_id=claim_b["inbox_id"]
        ).one()
        assignment_after = verify.get(models.EdgeDeviceTaskAssignment, assignment_b)
        assert assignment_after.revoked_at is not None
        assert ack_b.assignment_id == assignment_b
        assert ack_b.result == "ACCEPTED"
        assert ack_b.received_at <= assignment_after.revoked_at
        assert verify.query(models.EdgeDeviceTaskAssignmentEvent).filter_by(
            assignment_id=assignment_b
        ).order_by(models.EdgeDeviceTaskAssignmentEvent.id).all()[-1].event_type == "REVOKED"
        assert verify.query(models.EdgeDeviceEventProcessing).filter_by(
            id=claim_b["processing_id"], status="PROCESSED"
        ).count() == 1



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
        inventory_movement_count_before = db.query(models.InventoryMovement).count()

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
            now=reclaim_at + timedelta(seconds=2),
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

    worker_names = (f"ack-smoke-{suffix}-race-a", f"ack-smoke-{suffix}-race-b")
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(race_claim, ("race-a", "race-b")))
    winner_indexes = [index for index, claim in enumerate(claims) if claim is not None]
    assert len(winner_indexes) == 1, f"expected exactly one concurrent claim, got {len(winner_indexes)}"
    winner_index = winner_indexes[0]
    second_claim = claims[winner_index]
    second_worker = worker_names[winner_index]
    assert second_claim["inbox_id"] == inbox_ids[1]

    with SessionLocal() as tx:
        complete_edge_event_transactionally(
            tx,
            processing_id=second_claim["processing_id"],
            worker_id=second_worker,
            fencing_token=second_claim["fencing_token"],
            event=second_claim,
            handler=apply_edge_task_acknowledgement,
            now=concurrent_now + timedelta(seconds=1),
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
        assert completed.fingerprint_sha256 == ("0" * 63 + "1")
        task_after = verify.get(models.ReplenishmentTask, task_id)
        assert task_after.status == "PENDING"
        assert task_after.task_version == task_version
        assert task_after.completed_at is None
        assert verify.query(models.InventoryMovement).count() == inventory_movement_count_before
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

    _prove_revocation_ack_races(
        suffix=suffix, store_id=store_id, task_id=task_id, device_id=device_id,
        actor=actor, task_version=task_version, original_assignment_id=assignment_id,
    )

    print(
        "PostgreSQL Edge ACK smoke passed: atomic rollback/commit, replay rejection, "
        "single-winner concurrent claim, fencing, COMPLETED review-only semantics, "
        "no inventory side effects, append-only triggers and deterministic ACK/revocation lock ordering."
    )


if __name__ == "__main__":
    main()
