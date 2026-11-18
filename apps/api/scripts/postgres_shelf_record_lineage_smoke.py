"""Verify PostgreSQL enforces tenant lineage for shelf-scoped operational records."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import models
from app.database import SessionLocal


def _must_reject(db, statement: str, params: dict, description: str) -> None:
    try:
        db.execute(text(statement), params)
        db.commit()
    except DBAPIError:
        db.rollback()
    else:
        raise AssertionError(f"PostgreSQL accepted invalid shelf lineage: {description}")


def main() -> None:
    suffix = uuid4().hex[:12]
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        store_a = models.Store(code=f"PG-LINEAGE-A-{suffix}", name="Shelf lineage store A")
        store_b = models.Store(code=f"PG-LINEAGE-B-{suffix}", name="Shelf lineage store B")
        product = models.Product(sku=f"PG-LINEAGE-SKU-{suffix}", name="Shelf lineage product")
        db.add_all([store_a, store_b, product])
        db.flush()

        zone_a = models.Zone(store_id=store_a.id, name="Shelf lineage zone A")
        zone_b = models.Zone(store_id=store_b.id, name="Shelf lineage zone B")
        db.add_all([zone_a, zone_b])
        db.flush()

        shelf_a = models.Shelf(zone_id=zone_a.id, code=f"PG-LINEAGE-SHELF-{suffix}")
        db.add(shelf_a)
        db.flush()

        user = models.User(
            email=f"pg-lineage-admin-{suffix}@example.test",
            full_name="Shelf lineage smoke administrator",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        db.add(user)
        db.flush()

        alert = models.ObservationAlert(
            store_id=store_a.id,
            shelf_id=shelf_a.id,
            product_id=product.id,
            condition="LOW_STOCK",
            status="OPEN",
            first_seen_at=now,
            last_seen_at=now,
            confirmation_count=2,
            average_confidence=0.95,
            sources=["postgres-lineage-smoke"],
        )
        capture = models.CaptureSession(
            store_id=store_a.id,
            shelf_id=shelf_a.id,
            source_type="mobile",
            capture_mode="single",
            created_by_user_id=user.id,
        )
        task = models.ReplenishmentTask(
            store_id=store_a.id,
            shelf_id=shelf_a.id,
            product_id=product.id,
            requested_quantity=2,
        )
        db.add_all([alert, capture, task])
        db.commit()

        store_a_id, store_b_id = store_a.id, store_b.id
        zone_a_id, zone_b_id = zone_a.id, zone_b.id
        shelf_a_id = shelf_a.id
        alert_id, capture_id, task_id = alert.id, capture.id, task.id

    tables = (
        ("observation_alerts", alert_id, "product_id, condition, status, first_seen_at, last_seen_at, confirmation_count, average_confidence, sources, created_at, updated_at",
         ":product_id, 'LOW_STOCK', 'OPEN', :now, :now, 2, 0.95, '[]'::jsonb, :now, :now"),
        ("capture_sessions", capture_id, "source_type, capture_mode, started_at, created_by_user_id, created_at",
         "'mobile', 'single', :now, :user_id, :now"),
        ("replenishment_tasks", task_id, "product_id, priority, status, requested_quantity, created_at, updated_at",
         ":product_id, 'NORMAL', 'PENDING', 2, :now, :now"),
    )
    params = {
        "store_id": store_b_id,
        "shelf_id": shelf_a_id,
        "product_id": product.id,
        "now": now,
        "user_id": user.id,
    }

    with SessionLocal() as db:
        for table, _, columns, values in tables:
            _must_reject(
                db,
                f"INSERT INTO {table} (store_id, shelf_id, {columns}) VALUES (:store_id, :shelf_id, {values})",
                params,
                f"cross-store insert into {table}",
            )
        for table, record_id, _, _ in tables:
            _must_reject(
                db,
                f"UPDATE {table} SET store_id = :store_id WHERE id = :record_id",
                {"store_id": store_b_id, "record_id": record_id},
                f"cross-store update in {table}",
            )

        _must_reject(
            db,
            "UPDATE shelves SET zone_id = :zone_b WHERE id = :shelf_a",
            {"zone_b": zone_b_id, "shelf_a": shelf_a_id},
            "moving a shelf with dependent records to another store",
        )
        _must_reject(
            db,
            "UPDATE zones SET store_id = :store_b WHERE id = :zone_a",
            {"store_b": store_b_id, "zone_a": zone_a_id},
            "moving a zone with dependent records to another store",
        )

        persisted = {
            "observation_alerts": db.execute(
                text("SELECT COUNT(*) FROM observation_alerts WHERE id = :id AND store_id = :store_id AND shelf_id = :shelf_id"),
                {"id": alert_id, "store_id": store_a_id, "shelf_id": shelf_a_id},
            ).scalar_one(),
            "capture_sessions": db.execute(
                text("SELECT COUNT(*) FROM capture_sessions WHERE id = :id AND store_id = :store_id AND shelf_id = :shelf_id"),
                {"id": capture_id, "store_id": store_a_id, "shelf_id": shelf_a_id},
            ).scalar_one(),
            "replenishment_tasks": db.execute(
                text("SELECT COUNT(*) FROM replenishment_tasks WHERE id = :id AND store_id = :store_id AND shelf_id = :shelf_id"),
                {"id": task_id, "store_id": store_a_id, "shelf_id": shelf_a_id},
            ).scalar_one(),
        }
        assert persisted == {
            "observation_alerts": 1,
            "capture_sessions": 1,
            "replenishment_tasks": 1,
        }, persisted

    print(
        "PostgreSQL shelf record lineage smoke passed: cross-store INSERT/UPDATE "
        "and upstream shelf/zone moves were rejected; valid records remained intact."
    )


if __name__ == "__main__":
    main()
