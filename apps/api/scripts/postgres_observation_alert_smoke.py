"""Verify concurrent observation-alert persistence and append-only audit on PostgreSQL 16."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app


def main() -> None:
    suffix = uuid4().hex[:12]
    with TestClient(app) as client:
        store = client.post(
            "/api/v1/stores",
            json={"code": f"ALERT-CI-{suffix}", "name": "CI observation alerts"},
        )
        assert store.status_code == 201, store.text
        store_id = store.json()["id"]
        zone = client.post(
            "/api/v1/zones", json={"store_id": store_id, "name": "CI zone"},
        )
        assert zone.status_code == 201, zone.text
        shelf = client.post(
            "/api/v1/shelves",
            json={"zone_id": zone.json()["id"], "code": f"ALERT-{suffix}"},
        )
        assert shelf.status_code == 201, shelf.text
        shelf_id = shelf.json()["id"]
        product = client.post(
            "/api/v1/products",
            json={"sku": f"ALERT-SKU-{suffix}", "name": "CI alert product"},
        )
        assert product.status_code == 201, product.text
        product_id = product.json()["id"]
        assignment = client.post(
            "/api/v1/shelf-products",
            json={"shelf_id": shelf_id, "product_id": product_id},
        )
        assert assignment.status_code == 201, assignment.text

        now = datetime.now(timezone.utc)
        for seconds_ago in (60, 40, 20):
            response = client.post(
                "/api/v1/observations",
                json={
                    "shelf_id": shelf_id,
                    "product_id": product_id,
                    "source": "simulation",
                    "status": "LOW_STOCK",
                    "confidence": 0.95,
                    "observed_at": (now - timedelta(seconds=seconds_ago)).isoformat(),
                },
            )
            assert response.status_code == 201, response.text

        db = SessionLocal()
        try:
            user = models.User(
                email=f"alert-ci-{suffix}@example.test",
                store_id=store_id,
                full_name="CI Alert Supervisor",
                password_hash="not-used-in-ci",
                role="SUPERVISOR",
                is_active=True,
            )
            db.add(user)
            db.commit()
            actor = SimpleNamespace(
                id=user.id, role=user.role, store_id=user.store_id,
            )
        finally:
            db.close()

        original_request_user = main_module._request_user
        main_module._request_user = lambda db, request: actor
        try:
            params = {
                "product_id": product_id,
                "minimum_confirmations": 3,
                "minimum_interval_seconds": 10,
                "minimum_confidence": 0.6,
            }
            barrier = Barrier(2)

            def evaluate():
                barrier.wait(timeout=10)
                return client.post(
                    f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate",
                    params=params,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(lambda _: evaluate(), range(2)))

            assert all(response.status_code == 200 for response in responses), [
                response.text for response in responses
            ]
            alert_ids = {response.json()["id"] for response in responses}
            assert len(alert_ids) == 1, [response.json() for response in responses]
            alert_id = alert_ids.pop()

            listing = client.get(
                "/api/v1/observation-alerts",
                params={"shelf_id": shelf_id, "product_id": product_id},
            )
            assert listing.status_code == 200, listing.text
            assert len(listing.json()) == 1
            events = client.get(f"/api/v1/observation-alerts/{alert_id}/events")
            assert events.status_code == 200, events.text
            assert [event["event_type"] for event in events.json()] == ["CREATED"]

            # The database trigger, not merely application conventions, must
            # reject both mutation and deletion of audit records.
            audit_db = SessionLocal()
            try:
                for statement in (
                    text(
                        "UPDATE observation_alert_events "
                        "SET reason = 'tampered' WHERE alert_id = :alert_id"
                    ),
                    text(
                        "DELETE FROM observation_alert_events "
                        "WHERE alert_id = :alert_id"
                    ),
                ):
                    try:
                        audit_db.execute(statement, {"alert_id": alert_id})
                        audit_db.commit()
                    except DBAPIError:
                        audit_db.rollback()
                    else:
                        raise AssertionError(
                            "Observation alert audit trigger allowed mutation"
                        )
                persisted_count = audit_db.execute(
                    text(
                        "SELECT count(*) FROM observation_alert_events "
                        "WHERE alert_id = :alert_id"
                    ),
                    {"alert_id": alert_id},
                ).scalar_one()
                assert persisted_count == 1, persisted_count
            finally:
                audit_db.close()
        finally:
            main_module._request_user = original_request_user


if __name__ == "__main__":
    main()
