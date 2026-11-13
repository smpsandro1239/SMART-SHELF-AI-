"""Smoke-test the active-task partial unique index on a migrated PostgreSQL DB."""
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app import models


def main() -> None:
    suffix = uuid4().hex[:12]
    db = SessionLocal()
    contender = SessionLocal()
    try:
        store = models.Store(code=f"CI-{suffix}", name="CI concurrency smoke")
        product = models.Product(sku=f"CI-SKU-{suffix}", name="CI product")
        db.add_all([store, product])
        db.flush()
        zone = models.Zone(store_id=store.id, name="CI zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"CI-SHELF-{suffix}")
        db.add(shelf)
        db.flush()

        first = models.ReplenishmentTask(
            store_id=store.id,
            shelf_id=shelf.id,
            product_id=product.id,
            priority="NORMAL",
            status="PENDING",
        )
        db.add(first)
        db.commit()

        duplicate = models.ReplenishmentTask(
            store_id=store.id,
            shelf_id=shelf.id,
            product_id=product.id,
            priority="NORMAL",
            status="PENDING",
        )
        contender.add(duplicate)
        try:
            contender.commit()
        except IntegrityError:
            contender.rollback()
        else:
            raise AssertionError("PostgreSQL allowed a duplicate active task")

        first.status = "COMPLETED"
        db.commit()

        replacement = models.ReplenishmentTask(
            store_id=store.id,
            shelf_id=shelf.id,
            product_id=product.id,
            priority="NORMAL",
            status="PENDING",
        )
        db.add(replacement)
        db.commit()
        print("PostgreSQL active-task unique index: PASS")
    finally:
        contender.close()
        db.close()


if __name__ == "__main__":
    main()
