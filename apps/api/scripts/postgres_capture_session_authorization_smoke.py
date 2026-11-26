"""Verify capture-session tenant isolation against PostgreSQL with real JWTs.

Creates two stores and capture sessions, then checks supervisor scoping,
shelf filters, administrator visibility, and employee denial through HTTP.
"""
from threading import Event, Thread
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app, _lock_store_scoped_shelf
from app.security import create_access_token


def _bearer(user_id: int, role: str) -> dict[str, str]:
    token, _ = create_access_token(user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}




def _assert_zone_transfer_waits_for_shelf_write_lock() -> None:
    """Prove a zone transfer waits for the shelf write's ownership lock."""
    suffix = uuid4().hex[:12]
    setup = SessionLocal()
    try:
        store_a = models.Store(code=f"PG-SHELF-LOCK-A-{suffix}", name="Shelf lock A")
        store_b = models.Store(code=f"PG-SHELF-LOCK-B-{suffix}", name="Shelf lock B")
        setup.add_all([store_a, store_b])
        setup.flush()
        zone = models.Zone(store_id=store_a.id, name=f"Shelf lock zone {suffix}")
        setup.add(zone)
        setup.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"SHELF-LOCK-{suffix}")
        setup.add(shelf)
        setup.commit()
        store_a_id, store_b_id, zone_id, shelf_id = (
            store_a.id, store_b.id, zone.id, shelf.id
        )
    finally:
        setup.close()

    writer = SessionLocal()
    writer_pid = writer.execute(text("SELECT pg_backend_pid()")).scalar_one()
    actor = SimpleNamespace(id=None, role="SUPERVISOR", store_id=store_a_id)
    shelf_row, zone_row = _lock_store_scoped_shelf(writer, shelf_id, actor)
    assert shelf_row.id == shelf_id
    assert zone_row.store_id == store_a_id
    capture = models.CaptureSession(
        store_id=zone_row.store_id,
        shelf_id=shelf_row.id,
        source_type="mobile",
        capture_mode="single",
        started_at=models.utc_now(),
    )
    writer.add(capture)
    writer.flush()
    capture_id = capture.id

    started = Event()
    finished = Event()
    failures: list[BaseException] = []
    contender_pids: list[int] = []

    def transfer_zone() -> None:
        contender = SessionLocal()
        try:
            contender_pids.append(
                contender.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            started.set()
            contender.execute(
                text("UPDATE zones SET store_id = :store_id WHERE id = :zone_id"),
                {"store_id": store_b_id, "zone_id": zone_id},
            )
            contender.commit()
        except BaseException as exc:
            contender.rollback()
            failures.append(exc)
        finally:
            contender.close()
            finished.set()

    thread = Thread(target=transfer_zone, daemon=True)
    thread.start()
    assert started.wait(timeout=5), "zone transfer contender did not start"
    assert contender_pids, "zone transfer backend PID was not captured"

    observer = SessionLocal()
    deadline = monotonic() + 5
    observed_blocker = False
    try:
        while monotonic() < deadline and not finished.is_set():
            row = observer.execute(
                text(
                    """
                    SELECT wait_event_type, pg_blocking_pids(pid) AS blocking_pids
                    FROM pg_stat_activity
                    WHERE pid = :pid
                    """
                ),
                {"pid": contender_pids[0]},
            ).one_or_none()
            if (
                row is not None
                and row.wait_event_type == "Lock"
                and writer_pid in (row.blocking_pids or [])
            ):
                observed_blocker = True
                break
            sleep(0.01)
    finally:
        observer.close()

    assert observed_blocker, (
        "zone transfer did not report a PostgreSQL lock wait blocked by "
        f"shelf writer PID {writer_pid}; contender PID={contender_pids[0]}"
    )
    assert not finished.is_set(), "zone transfer completed before shelf write committed"

    writer.commit()
    writer.close()
    thread.join(timeout=10)
    assert finished.is_set(), "zone transfer remained blocked after shelf write commit"
    assert not failures, f"zone transfer failed after serialized shelf write: {failures}"

    verify = SessionLocal()
    try:
        persisted_capture = verify.get(models.CaptureSession, capture_id)
        moved_zone = verify.get(models.Zone, zone_id)
        assert persisted_capture is not None
        assert persisted_capture.store_id == store_a_id
        assert moved_zone is not None and moved_zone.store_id == store_b_id
    finally:
        verify.close()

def main() -> None:
    suffix = uuid4().hex[:12]
    db = SessionLocal()
    try:
        store_a = models.Store(code=f"PG-CAPTURE-A-{suffix}", name="Capture store A")
        store_b = models.Store(code=f"PG-CAPTURE-B-{suffix}", name="Capture store B")
        db.add_all([store_a, store_b])
        db.flush()

        zone_a = models.Zone(store_id=store_a.id, name="Capture zone A")
        zone_b = models.Zone(store_id=store_b.id, name="Capture zone B")
        db.add_all([zone_a, zone_b])
        db.flush()

        shelf_a = models.Shelf(zone_id=zone_a.id, code=f"CAP-A-{suffix}")
        shelf_b = models.Shelf(zone_id=zone_b.id, code=f"CAP-B-{suffix}")
        db.add_all([shelf_a, shelf_b])
        db.flush()

        supervisor = models.User(
            email=f"pg-capture-supervisor-{suffix}@example.test",
            full_name="Capture supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store_a.id,
            is_active=True,
        )
        admin = models.User(
            email=f"pg-capture-admin-{suffix}@example.test",
            full_name="Capture administrator",
            password_hash="smoke-test-only",
            role="ADMIN",
            store_id=None,
            is_active=True,
        )
        employee = models.User(
            email=f"pg-capture-employee-{suffix}@example.test",
            full_name="Capture employee",
            password_hash="smoke-test-only",
            role="EMPLOYEE",
            store_id=store_a.id,
            is_active=True,
        )
        db.add_all([supervisor, admin, employee])
        db.flush()

        session_a = models.CaptureSession(
            store_id=store_a.id,
            shelf_id=shelf_a.id,
            source_type="mobile",
            capture_mode="single",
            created_by_user_id=supervisor.id,
        )
        session_b = models.CaptureSession(
            store_id=store_b.id,
            shelf_id=shelf_b.id,
            source_type="mobile",
            capture_mode="single",
            created_by_user_id=admin.id,
        )
        db.add_all([session_a, session_b])
        db.commit()

        store_a_id = store_a.id
        store_b_id = store_b.id
        shelf_a_id = shelf_a.id
        shelf_b_id = shelf_b.id
        supervisor_id = supervisor.id
        admin_id = admin.id
        employee_id = employee.id
    finally:
        db.close()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(update={"app_env": "production"})
    try:
        with TestClient(app) as client:
            supervisor_headers = _bearer(supervisor_id, "SUPERVISOR")
            own = client.get("/api/v1/capture-sessions", headers=supervisor_headers)
            assert own.status_code == 200, own.text
            own_rows = own.json()
            assert len(own_rows) == 1, own_rows
            assert own_rows[0]["store_id"] == store_a_id, own_rows

            own_shelf = client.get(
                "/api/v1/capture-sessions",
                params={"shelf_id": shelf_a_id},
                headers=supervisor_headers,
            )
            assert own_shelf.status_code == 200, own_shelf.text
            assert len(own_shelf.json()) == 1, own_shelf.json()
            assert own_shelf.json()[0]["shelf_id"] == shelf_a_id

            foreign_shelf = client.get(
                "/api/v1/capture-sessions",
                params={"shelf_id": shelf_b_id},
                headers=supervisor_headers,
            )
            assert foreign_shelf.status_code == 200, foreign_shelf.text
            assert foreign_shelf.json() == [], foreign_shelf.json()

            admin_response = client.get(
                "/api/v1/capture-sessions",
                headers=_bearer(admin_id, "ADMIN"),
            )
            assert admin_response.status_code == 200, admin_response.text
            admin_rows = admin_response.json()
            visible_stores = {row["store_id"] for row in admin_rows}
            assert {store_a_id, store_b_id}.issubset(visible_stores), admin_rows

            employee_response = client.get(
                "/api/v1/capture-sessions",
                headers=_bearer(employee_id, "EMPLOYEE"),
            )
            assert employee_response.status_code == 403, employee_response.text

            created_own = client.post(
                "/api/v1/capture-sessions",
                json={"shelf_id": shelf_a_id, "source_type": "mobile"},
                headers=supervisor_headers,
            )
            assert created_own.status_code == 201, created_own.text
            assert created_own.json()["store_id"] == store_a_id
            created_foreign = client.post(
                "/api/v1/capture-sessions",
                json={"shelf_id": shelf_b_id, "source_type": "mobile"},
                headers=supervisor_headers,
            )
            assert created_foreign.status_code == 404, created_foreign.text
    finally:
        main_module.settings = original_settings

    _assert_zone_transfer_waits_for_shelf_write_lock()

    print(
        "PostgreSQL capture-session authorization and shelf ownership-lock smoke passed: "
        "SUPERVISOR is store-scoped, foreign shelf filter is empty, "
        "ADMIN sees both stores, and EMPLOYEE is denied."
    )


if __name__ == "__main__":
    main()
