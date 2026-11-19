"""Verify PostgreSQL planogram constraints and serialization of draft edits vs activation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
import time
from uuid import uuid4

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import SessionLocal
from app.shelf_planograms import (
    activate_planogram,
    create_draft_planogram,
    replace_draft_planogram_cells,
)


def _cell(code: str, product_id: int, *, x_min: float, x_max: float, facings: int):
    return {
        "cell_code": code,
        "row_index": 0,
        "column_index": 0 if x_min == 0 else 1,
        "x_min": x_min,
        "y_min": 0.0,
        "x_max": x_max,
        "y_max": 1.0,
        "expected_product_id": product_id,
        "expected_facings": facings,
    }


def _expect_integrity_error(db, operation, message: str) -> None:
    try:
        with db.begin_nested():
            operation()
            db.flush()
    except IntegrityError:
        return
    raise AssertionError(message)


def main() -> None:
    suffix = uuid4().hex[:12]
    with SessionLocal() as db:
        store = models.Store(code=f"PLANOGRAM-{suffix}", name="Planogram PostgreSQL smoke")
        db.add(store)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Planogram zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"PLANO-{suffix}")
        admin = models.User(
            email=f"planogram-{suffix}@example.test",
            full_name="Planogram smoke administrator",
            password_hash="not-a-real-password-hash",
            role="ADMIN",
            is_active=True,
        )
        product = models.Product(
            sku=f"PLANOGRAM-SKU-{suffix}",
            name="Planogram smoke product",
            is_active=True,
        )
        db.add_all([shelf, admin, product])
        db.flush()
        db.add(models.ShelfProduct(
            shelf_id=shelf.id,
            product_id=product.id,
            target_quantity=10,
            min_display_quantity=2,
        ))
        db.commit()
        shelf_id, actor_id, product_id = shelf.id, admin.id, product.id

    with SessionLocal() as db:
        first = create_draft_planogram(
            db,
            shelf_id=shelf_id,
            actor_user_id=actor_id,
            cells=[_cell("A1", product_id, x_min=0.0, x_max=0.5, facings=2)],
        )
        db.commit()
        first_id = first.id

        def invalid_count():
            db.add(models.ShelfPlanogramCell(
                planogram_id=first_id,
                cell_code="BAD-COUNT",
                row_index=0,
                column_index=1,
                x_min=0.5,
                y_min=0.0,
                x_max=0.75,
                y_max=1.0,
                expected_product_id=product_id,
                expected_facings=0,
            ))

        _expect_integrity_error(
            db, invalid_count,
            "PostgreSQL accepted expected_facings=0",
        )

        def missing_sku():
            db.add(models.ShelfPlanogramCell(
                planogram_id=first_id,
                cell_code="NO-SKU",
                row_index=0,
                column_index=1,
                x_min=0.5,
                y_min=0.0,
                x_max=0.75,
                y_max=1.0,
                expected_product_id=None,
                expected_facings=2,
            ))

        _expect_integrity_error(
            db, missing_sku,
            "PostgreSQL accepted expected_facings without expected_product_id",
        )
        db.commit()

        activate_planogram(
            db, planogram_id=first_id, actor_user_id=actor_id,
            reason="PostgreSQL smoke initial activation",
        )
        db.commit()

        def mutate_active_cell():
            db.execute(
                update(models.ShelfPlanogramCell)
                .where(models.ShelfPlanogramCell.planogram_id == first_id)
                .values(expected_facings=5)
            )

        _expect_integrity_error(
            db, mutate_active_cell,
            "PostgreSQL allowed mutation of an ACTIVE planogram cell",
        )
        db.commit()

        second = create_draft_planogram(
            db,
            shelf_id=shelf_id,
            actor_user_id=actor_id,
            cells=[_cell("B1", product_id, x_min=0.0, x_max=0.5, facings=2)],
        )
        db.commit()
        second_id = second.id

        def activate_without_retiring_previous():
            db.execute(
                update(models.ShelfPlanogram)
                .where(models.ShelfPlanogram.id == second_id)
                .values(
                    status="ACTIVE",
                    activated_by_user_id=actor_id,
                    activated_at=datetime.now(timezone.utc),
                    activation_reason="direct constraint probe",
                )
            )

        _expect_integrity_error(
            db, activate_without_retiring_previous,
            "PostgreSQL allowed two ACTIVE planograms on one shelf",
        )
        db.rollback()

        activate_planogram(
            db, planogram_id=second_id, actor_user_id=actor_id,
            reason="PostgreSQL smoke replacement activation",
        )
        db.commit()

        third = create_draft_planogram(
            db,
            shelf_id=shelf_id,
            actor_user_id=actor_id,
            cells=[_cell("C1", product_id, x_min=0.0, x_max=0.5, facings=2)],
        )
        db.commit()
        third_id = third.id

    replacement_ready = Event()
    release_replacement = Event()
    activation_started = Event()

    def replace_draft():
        with SessionLocal() as db:
            replace_draft_planogram_cells(
                db,
                planogram_id=third_id,
                actor_user_id=actor_id,
                cells=[_cell("C2", product_id, x_min=0.0, x_max=0.5, facings=4)],
            )
            replacement_ready.set()
            if not release_replacement.wait(timeout=15):
                raise TimeoutError("Timed out waiting to commit DRAFT cell replacement")
            db.commit()

    def activate_after_replacement():
        if not replacement_ready.wait(timeout=15):
            raise TimeoutError("DRAFT replacement did not acquire its locks")
        with SessionLocal() as db:
            activation_started.set()
            activate_planogram(
                db,
                planogram_id=third_id,
                actor_user_id=actor_id,
                reason="Concurrent activation smoke",
            )
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        replace_future = executor.submit(replace_draft)
        if not replacement_ready.wait(timeout=15):
            raise TimeoutError("DRAFT replacement did not become ready")
        activate_future = executor.submit(activate_after_replacement)
        if not activation_started.wait(timeout=15):
            raise TimeoutError("Activation thread did not start")
        time.sleep(0.3)
        if activate_future.done():
            raise AssertionError("Activation did not wait for the in-flight DRAFT replacement")
        release_replacement.set()
        replace_future.result(timeout=15)
        activate_future.result(timeout=15)

    with SessionLocal() as db:
        active = db.execute(
            select(models.ShelfPlanogram)
            .where(
                models.ShelfPlanogram.shelf_id == shelf_id,
                models.ShelfPlanogram.status == "ACTIVE",
            )
        ).scalar_one()
        assert active.id == third_id
        cells = db.query(models.ShelfPlanogramCell).filter_by(planogram_id=active.id).all()
        assert [(cell.cell_code, cell.expected_facings) for cell in cells] == [("C2", 4)]
        assert db.query(models.ShelfPlanogram).filter_by(
            shelf_id=shelf_id, status="ACTIVE"
        ).count() == 1

    print(
        "PostgreSQL planogram smoke passed: expected_facings constraints, "
        "active-cell immutability, one-active-per-shelf and DRAFT-edit/activation "
        "serialization verified."
    )


if __name__ == "__main__":
    main()
