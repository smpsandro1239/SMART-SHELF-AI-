"""Prove PostgreSQL 0099 row-lock serialization against hierarchy/link changes."""

from threading import Event, Thread
from time import monotonic, sleep
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


def _assert_blocked_then_rejected(
    operation, label: str
) -> tuple[Thread, Event, list[BaseException]]:
    started = Event()
    finished = Event()
    failures: list[BaseException] = []
    backend_pids: list[int] = []

    def contender():
        db = SessionLocal()
        try:
            backend_pids.append(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
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
    assert backend_pids, f"{label}: contender backend PID was not captured"

    # Observe PostgreSQL itself instead of inferring a lock wait from a fixed
    # sleep. The contender must be executing and waiting on a PostgreSQL lock.
    observer = SessionLocal()
    deadline = monotonic() + 5
    observed_wait: tuple[str | None, str | None] | None = None
    try:
        while monotonic() < deadline and not finished.is_set():
            row = observer.execute(
                text(
                    """
                    SELECT wait_event_type, wait_event
                    FROM pg_stat_activity
                    WHERE pid = :pid
                    """
                ),
                {"pid": backend_pids[0]},
            ).one_or_none()
            if row is not None and row.wait_event_type == "Lock":
                observed_wait = (row.wait_event_type, row.wait_event)
                break
            sleep(0.01)
    finally:
        observer.close()

    assert observed_wait is not None, (
        f"{label}: PostgreSQL did not report a lock wait for contender "
        f"backend PID {backend_pids[0]} within 5 seconds"
    )
    assert not finished.is_set(), (
        f"{label}: contender finished despite PostgreSQL reporting a lock wait"
    )
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

    # Exercise the reconciliation-specific observation lock separately
    # from the alert scenarios above. An upstream observation mutation must
    # wait for the reconciliation insert, then be rejected as retained evidence.
    setup = SessionLocal()
    try:
        reconciliation_zone = models.Zone(
            store_id=store_a_id,
            name=f"Reconciliation lineage zone {suffix}",
        )
        replacement_product = models.Product(
            sku=f"LINEAGE-REPLACEMENT-{suffix}",
            name="Replacement lineage product",
        )
        setup.add_all([reconciliation_zone, replacement_product])
        setup.flush()
        reconciliation_shelf = models.Shelf(
            zone_id=reconciliation_zone.id,
            code=f"RECON-LINEAGE-{suffix}",
        )
        setup.add(reconciliation_shelf)
        setup.flush()
        reconciliation_link = models.ShelfProduct(
            shelf_id=reconciliation_shelf.id,
            product_id=product_id,
            target_quantity=10,
            min_display_quantity=1,
        )
        actor = models.User(
            email=f"lineage-{suffix}@example.test",
            store_id=store_a_id,
            full_name="PostgreSQL lineage smoke",
            password_hash="test-only-not-used",
            role="ADMIN",
            is_active=True,
        )
        setup.add_all([reconciliation_link, actor])
        setup.flush()
        reconciliation_observation = models.Observation(
            shelf_id=reconciliation_shelf.id,
            product_id=product_id,
            source="postgres-0099-smoke",
            status="LOW_STOCK",
            confidence=0.95,
        )
        setup.add(reconciliation_observation)
        setup.commit()
        reconciliation_shelf_id = reconciliation_shelf.id
        reconciliation_observation_id = reconciliation_observation.id
        replacement_product_id = replacement_product.id
        actor_id = actor.id
    finally:
        setup.close()

    evidence = SessionLocal()
    evidence.add(
        models.InventoryReconciliation(
            store_id=store_a_id,
            shelf_id=reconciliation_shelf_id,
            product_id=product_id,
            observation_id=reconciliation_observation_id,
            display_target_quantity=10,
            display_quantity=2,
            comparison_status="MISMATCH",
            evidence={"source": "postgres-0099-smoke"},
            created_by_user_id=actor_id,
        )
    )
    evidence.flush()
    thread, finished, failures = _assert_blocked_then_rejected(
        lambda contender: contender.execute(
            text("UPDATE observations SET product_id = :product_id WHERE id = :observation_id"),
            {
                "product_id": replacement_product_id,
                "observation_id": reconciliation_observation_id,
            },
        ),
        "reconciliation observation mutation",
    )
    evidence.commit()
    thread.join(timeout=10)
    assert finished.is_set(), "observation mutation remained blocked after reconciliation commit"
    assert failures, "observation mutation unexpectedly succeeded after reconciliation committed"

    verify = SessionLocal()
    try:
        reconciliation = verify.query(models.InventoryReconciliation).filter_by(
            shelf_id=reconciliation_shelf_id,
            observation_id=reconciliation_observation_id,
        ).one()
        assert reconciliation.product_id == product_id
        assert verify.query(models.Observation).filter_by(
            id=reconciliation_observation_id,
            product_id=product_id,
        ).count() == 1
    finally:
        verify.close()

    print(
        "PostgreSQL 0099 lineage smoke passed: alert creation serialized with "
        "cross-store zone transfer and SKU unlink; reconciliation creation "
        "serialized with an upstream observation mutation. All competing writes "
        "waited on PostgreSQL locks and were rejected."
    )
    print(
        "PostgreSQL 0099 lineage smoke passed: alert and reconciliation evidence "
        "serialized with competing upstream mutations."
    )


if __name__ == "__main__":
    main()
