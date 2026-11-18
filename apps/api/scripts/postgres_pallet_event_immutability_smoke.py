"""Verify PostgreSQL protects physical pallet lifecycle events as append-only."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.models import (
    PalletRotationEvent,
    Product,
    ProductPackagingLevel,
    Store,
    StorePallet,
)


def assert_statement_rejected(statement: str, params: dict, description: str) -> None:
    with SessionLocal() as db:
        try:
            db.execute(text(statement), params)
            db.commit()
        except DBAPIError:
            db.rollback()
            return
    raise AssertionError(f"PostgreSQL allowed forbidden mutation: {description}")


def main() -> None:
    suffix = uuid4().hex[:10]
    with SessionLocal() as db:
        store = Store(code=f"PALLET-IMM-{suffix}", name="Pallet event immutability smoke")
        db.add(store)
        db.flush()
        product = Product(sku=f"PALLET-IMM-{suffix}", name="Pallet event immutability smoke")
        db.add(product)
        db.flush()
        level = ProductPackagingLevel(
            product_id=product.id,
            code=f"PALLET-IMM-{suffix}",
            name="Pallet event smoke level",
            package_type="PALLET",
            base_units_per_package=24,
            is_active=True,
        )
        db.add(level)
        db.flush()
        pallet = StorePallet(
            store_id=store.id,
            product_id=product.id,
            packaging_level_id=level.id,
            pallet_code=f"PALLET-IMM-{suffix}",
            base_quantity=24,
            status="READY",
            location_type="WAREHOUSE",
            location_code="IMMUTABILITY-TEST",
        )
        db.add(pallet)
        db.flush()
        event = PalletRotationEvent(
            pallet_id=pallet.id,
            event_type="REGISTERED",
            to_location_type="WAREHOUSE",
            to_location_code="IMMUTABILITY-TEST",
            quantity_before=0,
            quantity_after=24,
            reason="Initial registration for append-only smoke test",
        )
        db.add(event)
        db.commit()
        event_id = event.id

    assert_statement_rejected(
        "UPDATE pallet_rotation_events SET reason = 'tampered' WHERE id = :id",
        {"id": event_id},
        "pallet rotation event UPDATE",
    )
    assert_statement_rejected(
        "DELETE FROM pallet_rotation_events WHERE id = :id",
        {"id": event_id},
        "pallet rotation event DELETE",
    )

    with SessionLocal() as db:
        row = db.execute(
            text(
                "SELECT event_type, quantity_before, quantity_after, reason "
                "FROM pallet_rotation_events WHERE id = :id"
            ),
            {"id": event_id},
        ).one()
        assert row.event_type == "REGISTERED"
        assert float(row.quantity_before) == 0
        assert float(row.quantity_after) == 24
        assert row.reason == "Initial registration for append-only smoke test"

    print("PostgreSQL pallet event append-only smoke passed.")


if __name__ == "__main__":
    main()
