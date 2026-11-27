"""Prove concurrent human reviews of one Edge ACK serialize and remain idempotent."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main as main_module, models
from app.database import SessionLocal
from app.edge_task_acknowledgement_service import apply_edge_task_acknowledgement
from app.edge_task_assignment_service import create_edge_task_assignment
from app.main import app
from app.security import create_access_token


def create_fixture(suffix: str) -> tuple[int, int, int, int]:
    with SessionLocal() as db:
        store = models.Store(code=f"PG-EDGE-REVIEW-{suffix}", name="Edge ACK review concurrency smoke")
        db.add(store)
        db.flush()
        supervisor = models.User(
            email=f"pg-edge-review-{suffix}@example.test",
            full_name="Edge ACK review smoke supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store.id,
            is_active=True,
        )
        zone = models.Zone(store_id=store.id, name="Edge review smoke zone")
        product = models.Product(sku=f"EDGE-REVIEW-{suffix}", name="Review smoke product", unit="un")
        device = models.EdgeDevice(
            device_id=f"edge-review-device-{suffix}",
            store_id=store.id,
            device_type="robot",
            status="ACTIVE",
        )
        db.add_all([supervisor, zone, product, device])
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"EDGE-REVIEW-{suffix}")
        db.add(shelf)
        db.flush()
        task = models.ReplenishmentTask(
            store_id=store.id, shelf_id=shelf.id, product_id=product.id, status="PENDING",
        )
        db.add(task)
        db.commit()

        now = models.utc_now()
        create_edge_task_assignment(
            db, store_id=store.id, task_id=task.id, device_id=device.device_id,
            actor=supervisor, reason="Concurrency smoke assignment",
            valid_from=now, valid_until=None, allowed_actions=["COMPLETED"],
        )
        inbox = models.EdgeDeviceEventInbox(
            device_id=device.device_id,
            event_id=str(uuid4()),
            sequence_number=1,
            event_type="TASK_ACKNOWLEDGED",
            store_id=store.id,
            shelf_id=None,
            occurred_at=now,
            payload={"task_id": task.id, "task_version": task.task_version, "action": "COMPLETED"},
            fingerprint_sha256=uuid4().hex + uuid4().hex,
            received_at=now,
        )
        db.add(inbox)
        db.commit()
        apply_edge_task_acknowledgement(db, {
            "event_type": "TASK_ACKNOWLEDGED",
            "store_id": store.id,
            "device_id": device.device_id,
            "inbox_id": inbox.id,
            "event_id": inbox.event_id,
            "sequence_number": inbox.sequence_number,
            "fingerprint_sha256": inbox.fingerprint_sha256,
            "occurred_at": now,
            "payload": inbox.payload,
        })
        db.commit()
        acknowledgement = db.query(models.EdgeTaskAcknowledgement).one()
        return store.id, task.id, acknowledgement.id, supervisor.id


def wait_for_both_postgres_lock_waits(
    app_names: tuple[str, str], blocker_pid: int,
) -> None:
    deadline = monotonic() + 15
    last_state = None
    while monotonic() < deadline:
        with SessionLocal() as observer:
            rows = observer.execute(text("""
                SELECT application_name, wait_event_type, pg_blocking_pids(pid) AS blockers
                FROM pg_stat_activity
                WHERE application_name IN (:first, :second)
            """), {"first": app_names[0], "second": app_names[1]}).mappings().all()
        last_state = [dict(row) for row in rows]
        blocked = {
            row["application_name"]
            for row in rows
            if row["wait_event_type"] == "Lock" and blocker_pid in row["blockers"]
        }
        if blocked == set(app_names):
            return
        sleep(0.05)
    raise AssertionError(
        f"Both review requests did not block on the held task row; last={last_state!r}"
    )


def main() -> None:
    suffix = uuid4().hex[:10]
    _store_id, task_id, acknowledgement_id, supervisor_id = create_fixture(suffix)
    token, _ = create_access_token(user_id=supervisor_id, role="SUPERVISOR")
    blocker_name = f"edge-review-{suffix}-blocker"
    request_names = (
        f"edge-review-{suffix}-request-a",
        f"edge-review-{suffix}-request-b",
    )
    task_locked = Event()
    release_task = Event()
    request_started = {name: Event() for name in request_names}
    results: dict[str, object] = {}

    def hold_task_lock() -> int:
        with SessionLocal() as db:
            db.execute(text("SELECT set_config('application_name', :name, false)"), {"name": blocker_name})
            blocker_pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            db.query(models.ReplenishmentTask).filter(
                models.ReplenishmentTask.id == task_id,
            ).with_for_update().one()
            task_locked.set()
            if not release_task.wait(20):
                raise TimeoutError("review task lock was not released")
            return blocker_pid

    def scoped_get_db(request: Request):
        db = SessionLocal()
        try:
            name = request.headers.get("X-Smoke-Application", "")
            if name not in request_names:
                raise AssertionError("missing or invalid smoke application identity")
            db.execute(text("SELECT set_config('application_name', :name, false)"), {"name": name})
            request_started[name].set()
            yield db
        finally:
            db.close()

    def submit_review(name: str) -> None:
        payload = {
            "decision": "APPROVED",
            "reason": "Reposição confirmada por verificação presencial",
            "evidence_reference": f"evidence://concurrency/{suffix}",
            "idempotency_key": f"edge-review-{suffix}-same-key",
        }
        try:
            with TestClient(app) as client:
                response = client.post(
                    f"/api/v1/edge-task-acknowledgements/{acknowledgement_id}/reviews",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Smoke-Application": name,
                    },
                )
            results[name] = {"status_code": response.status_code, "body": response.json()}
        finally:
            pass

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(update={"app_env": "production"})
    try:
        app.dependency_overrides[main_module.get_db] = scoped_get_db
        with ThreadPoolExecutor(max_workers=3) as executor:
            blocker_future = executor.submit(hold_task_lock)
            assert task_locked.wait(10), "smoke transaction did not acquire the task row lock"
            blocker_pid = blocker_future.result(timeout=0) if blocker_future.done() else None
            if blocker_pid is None:
                # The holder is deliberately waiting; obtain its backend PID from pg_stat_activity.
                with SessionLocal() as observer:
                    blocker_pid = observer.execute(text(
                        "SELECT pid FROM pg_stat_activity WHERE application_name = :name"
                    ), {"name": blocker_name}).scalar_one()
            futures = [executor.submit(submit_review, name) for name in request_names]
            assert all(request_started[name].wait(10) for name in request_names), (
                "both authenticated review requests did not reach their DB sessions"
            )
            wait_for_both_postgres_lock_waits(request_names, blocker_pid)
            release_task.set()
            for future in futures:
                future.result(timeout=20)
            blocker_future.result(timeout=20)

        statuses = sorted(result["status_code"] for result in results.values())
        assert statuses == [200, 201], results
        with SessionLocal() as db:
            reviews = db.query(models.EdgeTaskAcknowledgementReview).filter_by(
                acknowledgement_id=acknowledgement_id,
            ).all()
            assert len(reviews) == 1, f"same idempotency key created {len(reviews)} rows"
            task = db.get(models.ReplenishmentTask, task_id)
            ack = db.get(models.EdgeTaskAcknowledgement, acknowledgement_id)
            assert task is not None and task.status == "PENDING" and task.task_version == 1
            assert ack is not None and ack.action == "COMPLETED" and ack.result == "REVIEW_REQUIRED"
            assert db.query(models.InventoryMovement).count() == 0
    finally:
        release_task.set()
        app.dependency_overrides.pop(main_module.get_db, None)
        main_module.settings = original_settings

    print(
        "PostgreSQL Edge ACK review concurrency smoke passed: both HTTP requests "
        "waited on the same task lock; the same idempotency key produced one "
        "immutable review (201 + 200), without task, ACK or inventory mutation."
    )


if __name__ == "__main__":
    main()
