"""Verify operational inventory snapshots cannot be updated or deleted."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.models import InventorySnapshot, Product, Store


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
        store = Store(code=f"IMM-{suffix}", name="Inventory immutability smoke")
        db.add(store)
        db.flush()
        product = Product(sku=f"IMM-{suffix}", name="Inventory immutability smoke")
        db.add(product)
        db.flush()
        snapshot = InventorySnapshot(
            store_id=store.id,
            product_id=product.id,
            on_hand_quantity=12,
            reserved_quantity=2,
            source="ERP",
            external_reference=f"IMM-{suffix}",
        )
        db.add(snapshot)
        db.commit()
        snapshot_id = snapshot.id

    assert_statement_rejected(
        "UPDATE inventory_snapshots SET on_hand_quantity = 0 WHERE id = :id",
        {"id": snapshot_id},
        "inventory snapshot UPDATE",
    )
    assert_statement_rejected(
        "DELETE FROM inventory_snapshots WHERE id = :id",
        {"id": snapshot_id},
        "inventory snapshot DELETE",
    )

    with SessionLocal() as db:
        row = db.execute(
            text(
                "SELECT on_hand_quantity, reserved_quantity "
                "FROM inventory_snapshots WHERE id = :id"
            ),
            {"id": snapshot_id},
        ).one()
        assert float(row.on_hand_quantity) == 12
        assert float(row.reserved_quantity) == 2


if __name__ == "__main__":
    main()
