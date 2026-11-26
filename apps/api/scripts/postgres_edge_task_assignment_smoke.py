"""Prove PostgreSQL serialization and atomic audit for Edge task assignments."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app


def main() -> None:
    suffix = uuid4().hex[:12]
    db = SessionLocal()
    try:
        store = models.Store(code=f"EDGE-ASSIGN-{suffix}", name="Edge assignment smoke")
        db.add(store)
        db.flush()
        user = models.User(
            email=f"edge-assignment-{suffix}@example.test",
            store_id=store.id,
            full_name="CI Supervisor",
            password_hash="not-used-in-smoke",
            role="SUPERVISOR",
            is_active=True,
        )
        zone = models.Zone(store_id=store.id, name="Edge assignment zone")
        product = models.Product(sku=f"EDGE-SKU-{suffix}", name="Edge assignment product")
        device = models.EdgeDevice(
            device_id=f"edge-device-{suffix}",
            store_id=store.id,
            device_type="fixed_camera",
            status="ACTIVE",
        )
        db.add_all([user, zone, product, device])
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"EDGE-SHELF-{suffix}")
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
    finally:
        db.close()

    original_request_user = main_module._request_user
    main_module._request_user = lambda db, request: actor
    try:
        with TestClient(app) as client:
            start = datetime.now(timezone.utc)
            payload = {
                "reason": "CI concorrência de associação",
                "valid_from": start.isoformat(),
                "valid_until": (start + timedelta(hours=2)).isoformat(),
            }
            url = (
                f"/api/v1/stores/{store_id}/edge-devices/{device_id}"
                f"/tasks/{task_id}/assignment"
            )
            barrier = Barrier(2)

            def create():
                barrier.wait(timeout=10)
                return client.post(url, json=payload)

            with ThreadPoolExecutor(max_workers=2) as executor:
                create_responses = list(executor.map(lambda _: create(), range(2)))

            created = [r for r in create_responses if r.status_code == 201]
            conflicts = [r for r in create_responses if r.status_code == 409]
            assert len(created) == 1, [(r.status_code, r.text) for r in create_responses]
            assert len(conflicts) == 1, [(r.status_code, r.text) for r in create_responses]
            assignment_id = created[0].json()["id"]

            revoke_url = f"/api/v1/edge-task-assignments/{assignment_id}/revoke"
            revoke_barrier = Barrier(2)

            def revoke():
                revoke_barrier.wait(timeout=10)
                return client.post(
                    revoke_url,
                    json={"reason": "CI revogação concorrente"},
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                revoke_responses = list(executor.map(lambda _: revoke(), range(2)))

            revoked = [r for r in revoke_responses if r.status_code == 200]
            revoke_conflicts = [r for r in revoke_responses if r.status_code == 409]
            assert len(revoked) == 1, [(r.status_code, r.text) for r in revoke_responses]
            assert len(revoke_conflicts) == 1, [(r.status_code, r.text) for r in revoke_responses]
    finally:
        main_module._request_user = original_request_user

    verify = SessionLocal()
    try:
        events = (
            verify.query(models.EdgeDeviceTaskAssignmentEvent)
            .filter_by(assignment_id=assignment_id)
            .order_by(models.EdgeDeviceTaskAssignmentEvent.id)
            .all()
        )
        assert [event.event_type for event in events] == ["CREATED", "REVOKED"]
        assignment = verify.get(models.EdgeDeviceTaskAssignment, assignment_id)
        assert assignment is not None and assignment.revoked_at is not None
    finally:
        verify.close()

    print(
        "PostgreSQL Edge assignment concurrency smoke passed: one active "
        "assignment and one CREATED/REVOKED audit pair under concurrent requests."
    )


if __name__ == "__main__":
    main()
