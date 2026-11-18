"""Prove PostgreSQL serializes legal-hold and purge-schedule HTTP transitions.

The first race commits a legal hold while a purge-schedule request waits on the
image row; scheduling must re-check the refreshed row and return HTTP 409.
The inverse race commits a purge schedule while a legal-hold request waits;
the hold must succeed without clearing the scheduled date or policy.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token


def create_fixture(suffix: str) -> tuple[int, int, int]:
    with SessionLocal() as db:
        store = models.Store(
            code=f"PG-RETENTION-RACE-{suffix}",
            name="PostgreSQL retention concurrency smoke",
        )
        db.add(store)
        db.flush()
        admin = models.User(
            email=f"pg-retention-race-{suffix}@example.test",
            full_name="Retention concurrency smoke administrator",
            password_hash="smoke-test-only",
            role="ADMIN",
            store_id=store.id,
            is_active=True,
        )
        db.add(admin)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Retention race zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"PG-RETENTION-RACE-{suffix}")
        db.add(shelf)
        db.flush()
        image_ids = []
        for label in ("hold-first", "schedule-first"):
            image = models.ShelfImage(
                shelf_id=shelf.id,
                original_filename=f"retention-race-{label}.jpg",
                storage_path=f"/tmp/retention-race-{suffix}-{label}.jpg",
                mime_type="image/jpeg",
                file_size_bytes=10,
                sha256="f" * 64,
                analysis_status="COMPLETED",
                retention_status="RESTRICTED",
            )
            db.add(image)
            db.flush()
            image_ids.append(image.id)
        db.commit()
        return image_ids[0], image_ids[1], admin.id


def run_serialized_race(
    *,
    image_id: int,
    application_name: str,
    token: str,
    mutate_locked_image,
    endpoint: str,
    payload: dict,
    expected_status: int,
) -> dict:
    image_locked = Event()
    allow_commit = Event()
    request_started = Event()
    request_finished = Event()
    result: dict[str, object] = {}

    def lock_holder() -> None:
        with SessionLocal() as db:
            image = (
                db.query(models.ShelfImage)
                .filter(models.ShelfImage.id == image_id)
                .with_for_update()
                .one()
            )
            image_locked.set()
            if not allow_commit.wait(timeout=20):
                raise TimeoutError("retention race lock holder was not released")
            mutate_locked_image(db, image)
            db.commit()

    def scoped_get_db():
        db = SessionLocal()
        try:
            db.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": application_name},
            )
            request_started.set()
            yield db
        finally:
            db.close()

    def invoke_endpoint() -> None:
        app.dependency_overrides[main_module.get_db] = scoped_get_db
        try:
            with TestClient(app) as client:
                response = client.post(
                    endpoint,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
            result["status_code"] = response.status_code
            result["body"] = response.json()
        finally:
            app.dependency_overrides.pop(main_module.get_db, None)
            request_finished.set()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(update={"app_env": "production"})
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            holder_future = executor.submit(lock_holder)
            request_future = None
            try:
                assert image_locked.wait(timeout=10), "lock holder did not acquire image row"
                request_future = executor.submit(invoke_endpoint)
                assert request_started.wait(timeout=10), "retention HTTP request did not start"

                deadline = monotonic() + 12
                observed_blocker = False
                while monotonic() < deadline:
                    with SessionLocal() as monitor:
                        activity = monitor.execute(
                            text(
                                "SELECT wait_event_type, pg_blocking_pids(pid) "
                                "FROM pg_stat_activity WHERE application_name = :name"
                            ),
                            {"name": application_name},
                        ).first()
                    if activity is not None and activity[0] == "Lock" and activity[1]:
                        observed_blocker = True
                        break
                    if request_finished.is_set():
                        break
                    sleep(0.05)

                assert observed_blocker, "HTTP request did not wait on the shelf-image row lock"
                assert not request_finished.is_set(), "HTTP request returned before competing commit"
            finally:
                allow_commit.set()

            holder_future.result(timeout=15)
            if request_future is not None:
                request_future.result(timeout=15)
    finally:
        app.dependency_overrides.pop(main_module.get_db, None)
        main_module.settings = original_settings

    assert result.get("status_code") == expected_status, result
    return result


def main() -> None:
    suffix = uuid4().hex[:10]
    hold_first_id, schedule_first_id, admin_id = create_fixture(suffix)
    token, _ = create_access_token(user_id=admin_id, role="ADMIN")
    scheduled_at = (models.utc_now() + timedelta(days=30)).astimezone(timezone.utc)

    def commit_legal_hold(db, image) -> None:
        image.legal_hold = True
        db.add(models.ShelfImageRetentionEvent(
            shelf_image_id=image.id,
            event_type="LEGAL_HOLD_APPLIED",
            from_status="RESTRICTED",
            to_status="RESTRICTED",
            actor_user_id=admin_id,
            reason="PostgreSQL concurrent retention smoke",
        ))

    schedule_result = run_serialized_race(
        image_id=hold_first_id,
        application_name=f"ss-retention-hold-first-{suffix}",
        token=token,
        mutate_locked_image=commit_legal_hold,
        endpoint=f"/api/v1/shelf-images/{hold_first_id}/retention/purge-schedule",
        payload={
            "purge_not_before": scheduled_at.isoformat(),
            "policy_version": "pg-retention-race-v1",
            "reason": "Schedule request racing with legal hold",
        },
        expected_status=409,
    )
    assert "legal hold" in str(schedule_result.get("body", {})).lower()

    def commit_purge_schedule(db, image) -> None:
        image.purge_not_before = scheduled_at
        image.retention_policy_version = "pg-retention-race-v1"
        image.retention_reason = "PostgreSQL concurrent retention smoke"
        db.add(models.ShelfImageRetentionEvent(
            shelf_image_id=image.id,
            event_type="PURGE_SCHEDULED",
            from_status="RESTRICTED",
            to_status="RESTRICTED",
            actor_user_id=admin_id,
            reason="PostgreSQL concurrent retention smoke",
        ))

    run_serialized_race(
        image_id=schedule_first_id,
        application_name=f"ss-retention-schedule-first-{suffix}",
        token=token,
        mutate_locked_image=commit_purge_schedule,
        endpoint=f"/api/v1/shelf-images/{schedule_first_id}/retention/legal-hold/apply",
        payload={"reason": "Legal hold request racing with scheduled purge"},
        expected_status=200,
    )

    with SessionLocal() as db:
        hold_first = db.get(models.ShelfImage, hold_first_id)
        schedule_first = db.get(models.ShelfImage, schedule_first_id)
        assert hold_first is not None and hold_first.legal_hold is True
        assert hold_first.purge_not_before is None
        assert schedule_first is not None and schedule_first.legal_hold is True
        assert schedule_first.purge_not_before is not None
        assert schedule_first.purge_not_before.replace(tzinfo=timezone.utc) == scheduled_at
        assert schedule_first.retention_policy_version == "pg-retention-race-v1"

        first_events = (
            db.query(models.ShelfImageRetentionEvent)
            .filter(models.ShelfImageRetentionEvent.shelf_image_id == hold_first_id)
            .order_by(models.ShelfImageRetentionEvent.id)
            .all()
        )
        second_events = (
            db.query(models.ShelfImageRetentionEvent)
            .filter(models.ShelfImageRetentionEvent.shelf_image_id == schedule_first_id)
            .order_by(models.ShelfImageRetentionEvent.id)
            .all()
        )
        assert [event.event_type for event in first_events] == ["LEGAL_HOLD_APPLIED"]
        assert [event.event_type for event in second_events] == [
            "PURGE_SCHEDULED",
            "LEGAL_HOLD_APPLIED",
        ]
        assert all(event.actor_user_id == admin_id for event in first_events + second_events)

    print(
        "PostgreSQL retention concurrency smoke passed: purge scheduling was "
        "rejected after a competing legal hold committed; applying a legal hold "
        "after a competing schedule committed preserved its date, policy and audit history."
    )


if __name__ == "__main__":
    main()
