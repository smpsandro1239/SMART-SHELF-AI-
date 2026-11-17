"""Verify PostgreSQL prevents concurrent duplicate active packaging units."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app import models
from app.database import SessionLocal


def race_for_flag(product_id: int, suffix: str, flag: str) -> None:
    barrier = Barrier(2)

    def insert(index: int) -> str:
        db = SessionLocal()
        try:
            level = models.ProductPackagingLevel(
                product_id=product_id,
                code=f"RACE-{suffix}-{index}",
                name=f"Concurrent {flag} {index}",
                package_type="CASE",
                base_units_per_package=6 + index,
                is_ordering_unit=flag == "ordering",
                is_replenishment_unit=flag == "replenishment",
                is_active=True,
            )
            db.add(level)
            barrier.wait(timeout=10)
            db.commit()
            return "created"
        except IntegrityError:
            db.rollback()
            return "conflict"
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(insert, (1, 2)))

    assert sorted(outcomes) == ["conflict", "created"], (flag, outcomes)


def main() -> None:
    suffix = uuid4().hex[:12]
    db = SessionLocal()
    try:
        product = models.Product(
            sku=f"PACKAGING-RACE-{suffix}",
            name="Packaging concurrency smoke product",
        )
        db.add(product)
        db.commit()
        product_id = product.id
    finally:
        db.close()

    race_for_flag(product_id, suffix, "ordering")
    race_for_flag(product_id, suffix, "replenishment")

    verify = SessionLocal()
    try:
        levels = verify.query(models.ProductPackagingLevel).filter_by(
            product_id=product_id, is_active=True
        ).all()
        ordering_count = sum(level.is_ordering_unit for level in levels)
        replenishment_count = sum(level.is_replenishment_unit for level in levels)
        assert ordering_count == 1, ordering_count
        assert replenishment_count == 1, replenishment_count
    finally:
        verify.close()

    print(
        "PostgreSQL packaging concurrency smoke passed: each active ordering "
        "and replenishment flag has exactly one persisted row."
    )


if __name__ == "__main__":
    main()
