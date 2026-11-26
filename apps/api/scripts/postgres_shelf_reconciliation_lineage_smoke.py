"""Prove PostgreSQL 0099 row-lock serialization against hierarchy/link changes."""

from threading import Event, Thread
from time import sleep
from uuid import uuid4

from sqlalchemy import text

from app import models
from app.database import SessionLocal


def _alert(store_id: int, shelf_id: int, product_id: int, condition: str):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return models.ObservationAlert(
        store_id=store_id,
        shelf_id=shelf_id,
        product_id=product_id,
        condition=condition,
        status="OPEN",
        first_seen_at=now,
        last_seen_at=now,
        confirmation_count=2,
        average_confidence=0.95,
        sources=["postgres-0099-smoke"],
        created_at=now,
        updated_at=now,
    )


def _assert_blocked_then_rejected(operation, label: str) -> None:
    started = Event()
    finished = Event()
    failures: list[BaseException] = []

    def contender():
        db = SessionLocal()
        try:
            started.set()
            operation(db)
            db.commit()
        except BaseException as exc:  # capture database constraint/trigger rejection
            db.rollback()
            failures.append(exc)
        finally:
            db.close()
            finished.set()

    thread = Thread(target=contender, daemon=True)
    thread.start()
    assert started.wait(timeout=5), f"{label}: contender did not start"
    sleep(0.2)
    assert not finished.is_set(), f"{label}: competing write did not wait for source-row lock"
    return thread, finished, failures


def main() -> None:
    suffix = uuid4().hex[:10]
    db = SessionLocal()
    try:
        store_a = models.Store(code=f"LINEAGE-A-{suffix}", name="Lineage A")
        store_b = models.Store(code=f"LINEAGE-B-{suffix}", name="Lineage B")
        db.add_all([store_a, store_b])
        db.flush()
        zone = models.Zone(store_id=store_a.id, name=f"Lineage zone {suffix}")
        product = models.Product(sku=f"LINEAGE-{suffix}", name="Lineage product")
        db.add_all([zone, product])
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"LINEAGE-{suffix}")
        db.add(shelf)
        db.flush()
        link = models.ShelfProduct(
            shelf_id=shelf.id,
            product_id=product.id,
            target_quantity=10,
            min_display_quantity=1,
        )
        db.add(link)
        db.commit()
        store_a_id, store_b_id = store_a.id, store_b.id
        zone_id, shelf_id, product_id, link_id = zone.id, shelf.id, product.id, link.id
    finally:
        db.close()

    # Evidence insertion locks shelf and zone FOR SHARE. A cross-store transfer
    # must wait, then fail after the evidence transaction commits.
    evidence = SessionLocal()
    evidence.add(_alert(store_a_id, shelf_id, product_id, "EMPTY"))
    evidence.flush()

    thread, finished, failures = _assert_blocked_then_rejected(
        lambda contender: contender.execute(
            text("UPDATE zones SET store_id = :store_id WHERE id = :zone_id"),
            {"store_id": store_b_id, "zone_id": zone_id},
        ),
        "zone transfer",
    )
    evidence.commit()
    thread.join(timeout=10)
    assert finished.is_set(), "zone transfer remained blocked after evidence commit"
    assert failures, "zone transfer unexpectedly succeeded after alert evidence committed"

    # A second evidence insert locks the shelf_products row FOR SHARE. Deleting
    # that association must wait and then fail because retained evidence exists.
    evidence = SessionLocal()
    evidence.add(_alert(store_a_id, shelf_id, product_id, "DAMAGED"))
    evidence.flush()
    thread, finished, failures = _assert_blocked_then_rejected(
        lambda contender: contender.execute(
            text("DELETE FROM shelf_products WHERE id = :link_id"),
            {"link_id": link_id},
        ),
        "shelf SKU unlink",
    )
    evidence.commit()
    thread.join(timeout=10)
    assert finished.is_set(), "shelf SKU unlink remained blocked after evidence commit"
    assert failures, "shelf SKU association was unexpectedly deleted"

    verify = SessionLocal()
    try:
        assert verify.query(models.ObservationAlert).filter_by(shelf_id=shelf_id).count() == 2
        assert verify.query(models.ShelfProduct).filter_by(id=link_id).count() == 1
        assert verify.query(models.Zone).filter_by(id=zone_id).one().store_id == store_a_id
    finally:
        verify.close()

    print(
        "PostgreSQL 0099 lineage smoke passed: cross-store zone transfer and "
        "SKU unlink both waited for evidence-row locks and were rejected."
    )


if __name__ == "__main__":
    main()
