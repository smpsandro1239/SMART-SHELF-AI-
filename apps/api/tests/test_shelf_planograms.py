"""Domain-service tests for versioned shelf planograms."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models
from app.shelf_planograms import (
    ShelfPlanogramError,
    activate_planogram,
    create_draft_planogram,
    load_active_planogram_for_shelf,
    retire_planogram,
)


@pytest.fixture
def planogram_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        store = models.Store(code="PLANOGRAM-STORE", name="Planogram Store")
        db.add(store)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Aisle A")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code="A-01")
        db.add(shelf)
        admin = models.User(
            email="planogram-admin@example.test",
            store_id=store.id,
            full_name="Planogram Admin",
            password_hash="not-a-real-password-hash",
            role="ADMIN",
            is_active=True,
        )
        supervisor = models.User(
            email="planogram-supervisor@example.test",
            store_id=store.id,
            full_name="Planogram Supervisor",
            password_hash="not-a-real-password-hash",
            role="SUPERVISOR",
            is_active=True,
        )
        other_supervisor = models.User(
            email="other-planogram-supervisor@example.test",
            store_id=999,
            full_name="Other Supervisor",
            password_hash="not-a-real-password-hash",
            role="SUPERVISOR",
            is_active=True,
        )
        employee = models.User(
            email="planogram-employee@example.test",
            store_id=store.id,
            full_name="Planogram Employee",
            password_hash="not-a-real-password-hash",
            role="EMPLOYEE",
            is_active=True,
        )
        db.add_all([admin, supervisor, other_supervisor, employee])
        product = models.Product(sku="PLANOGRAM-001", name="Planogram Product", is_active=True)
        inactive_product = models.Product(sku="PLANOGRAM-002", name="Inactive Product", is_active=False)
        db.add_all([product, inactive_product])
        db.flush()
        db.add(models.ShelfProduct(
            shelf_id=shelf.id,
            product_id=product.id,
            target_quantity=10,
            min_display_quantity=2,
        ))
        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="calibration.png",
            storage_path="100/calibration.png",
            mime_type="image/png",
            file_size_bytes=100,
            sha256="a" * 64,
            analysis_status="COMPLETED",
            retention_status="ACTIVE",
        )
        restricted_image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="restricted.png",
            storage_path="100/restricted.png",
            mime_type="image/png",
            file_size_bytes=100,
            sha256="b" * 64,
            analysis_status="COMPLETED",
            retention_status="RESTRICTED",
        )
        db.add_all([image, restricted_image])
        db.flush()
        yield {
            "db": db,
            "shelf": shelf,
            "admin": admin,
            "supervisor": supervisor,
            "other_supervisor": other_supervisor,
            "employee": employee,
            "product": product,
            "inactive_product": inactive_product,
            "image": image,
            "restricted_image": restricted_image,
        }
        db.rollback()
    Base.metadata.drop_all(engine)
    engine.dispose()


def cell(code="A1", *, row=0, column=0, x1=0.0, y1=0.0, x2=0.5, y2=1.0, product_id=None):
    return {
        "cell_code": code,
        "row_index": row,
        "column_index": column,
        "x_min": x1,
        "y_min": y1,
        "x_max": x2,
        "y_max": y2,
        "expected_product_id": product_id,
    }


def test_create_draft_planogram_versions_cells_and_scope(planogram_db):
    db = planogram_db["db"]
    shelf = planogram_db["shelf"]
    supervisor = planogram_db["supervisor"]
    product = planogram_db["product"]

    first = create_draft_planogram(
        db,
        shelf_id=shelf.id,
        actor_user_id=supervisor.id,
        cells=[cell(product_id=product.id)],
    )
    second = create_draft_planogram(
        db,
        shelf_id=shelf.id,
        actor_user_id=supervisor.id,
        cells=[cell("B1", product_id=product.id)],
    )

    assert (first.version, first.status) == (1, "DRAFT")
    assert (second.version, second.status) == (2, "DRAFT")
    assert first.cells[0].expected_product_id == product.id

    with pytest.raises(ShelfPlanogramError, match="Access to this shelf"):
        create_draft_planogram(
            db,
            shelf_id=shelf.id,
            actor_user_id=planogram_db["other_supervisor"].id,
            cells=[cell()],
        )
    with pytest.raises(ShelfPlanogramError, match="Only ADMIN or SUPERVISOR"):
        create_draft_planogram(
            db,
            shelf_id=shelf.id,
            actor_user_id=planogram_db["employee"].id,
            cells=[cell()],
        )


def test_create_draft_rejects_overlapping_cells_and_unassigned_skus(planogram_db):
    db = planogram_db["db"]
    shelf = planogram_db["shelf"]
    admin = planogram_db["admin"]
    product = planogram_db["product"]
    inactive = planogram_db["inactive_product"]

    with pytest.raises(ShelfPlanogramError, match="must not overlap"):
        create_draft_planogram(
            db,
            shelf_id=shelf.id,
            actor_user_id=admin.id,
            cells=[
                cell("A1", x1=0.0, x2=0.6, product_id=product.id),
                cell("A2", row=0, column=1, x1=0.5, x2=1.0, product_id=product.id),
            ],
        )
    with pytest.raises(ShelfPlanogramError, match="active and assigned"):
        create_draft_planogram(
            db,
            shelf_id=shelf.id,
            actor_user_id=admin.id,
            cells=[cell(product_id=inactive.id)],
        )
    with pytest.raises(ShelfPlanogramError, match="unique"):
        create_draft_planogram(
            db,
            shelf_id=shelf.id,
            actor_user_id=admin.id,
            cells=[cell("A1"), cell("A1", row=1, column=1, x1=0.5, x2=1.0)],
        )


def test_image_calibration_is_bound_to_active_image_digest_and_shelf(planogram_db):
    db = planogram_db["db"]
    shelf = planogram_db["shelf"]
    admin = planogram_db["admin"]
    image = planogram_db["image"]
    restricted = planogram_db["restricted_image"]

    plan = create_draft_planogram(
        db,
        shelf_id=shelf.id,
        actor_user_id=admin.id,
        cells=[cell()],
        calibration_source="IMAGE",
        calibration_image_id=image.id,
        calibration_image_sha256=image.sha256,
    )
    assert plan.calibration_image_id == image.id
    with pytest.raises(ShelfPlanogramError, match="not ACTIVE"):
        create_draft_planogram(
            db,
            shelf_id=shelf.id,
            actor_user_id=admin.id,
            cells=[cell("B1")],
            calibration_source="IMAGE",
            calibration_image_id=restricted.id,
            calibration_image_sha256=restricted.sha256,
        )
    with pytest.raises(ShelfPlanogramError, match="does not match"):
        create_draft_planogram(
            db,
            shelf_id=shelf.id,
            actor_user_id=admin.id,
            cells=[cell("C1")],
            calibration_source="IMAGE",
            calibration_image_id=image.id,
            calibration_image_sha256="f" * 64,
        )


def test_activation_retires_previous_version_and_load_revalidates_sources(planogram_db):
    db = planogram_db["db"]
    shelf = planogram_db["shelf"]
    admin = planogram_db["admin"]
    image = planogram_db["image"]

    first = create_draft_planogram(
        db,
        shelf_id=shelf.id,
        actor_user_id=admin.id,
        cells=[cell()],
        calibration_source="IMAGE",
        calibration_image_id=image.id,
        calibration_image_sha256=image.sha256,
    )
    activate_planogram(db, planogram_id=first.id, actor_user_id=admin.id, reason="camera calibrated")
    db.flush()
    assert load_active_planogram_for_shelf(
        db, shelf_id=shelf.id, actor_user_id=admin.id
    ).id == first.id

    second = create_draft_planogram(
        db,
        shelf_id=shelf.id,
        actor_user_id=admin.id,
        cells=[cell("B1")],
    )
    activate_planogram(db, planogram_id=second.id, actor_user_id=admin.id, reason="new shelf layout")
    db.flush()
    assert first.status == "RETIRED"
    assert second.status == "ACTIVE"
    assert load_active_planogram_for_shelf(
        db, shelf_id=shelf.id, actor_user_id=admin.id
    ).id == second.id


def test_retirement_allowed_after_calibration_source_becomes_restricted(planogram_db):
    db = planogram_db["db"]
    shelf = planogram_db["shelf"]
    admin = planogram_db["admin"]
    image = planogram_db["image"]

    plan = create_draft_planogram(
        db,
        shelf_id=shelf.id,
        actor_user_id=admin.id,
        cells=[cell()],
        calibration_source="IMAGE",
        calibration_image_id=image.id,
        calibration_image_sha256=image.sha256,
    )
    activate_planogram(db, planogram_id=plan.id, actor_user_id=admin.id, reason="initial approval")
    image.retention_status = "RESTRICTED"
    db.flush()

    with pytest.raises(ShelfPlanogramError, match="not ACTIVE"):
        load_active_planogram_for_shelf(db, shelf_id=shelf.id, actor_user_id=admin.id)

    retired = retire_planogram(
        db, planogram_id=plan.id, actor_user_id=admin.id, reason="source restricted"
    )
    assert retired.status == "RETIRED"


def test_active_planogram_refuses_products_removed_from_shelf_assignment(planogram_db):
    db = planogram_db["db"]
    shelf = planogram_db["shelf"]
    admin = planogram_db["admin"]
    product = planogram_db["product"]

    plan = create_draft_planogram(
        db,
        shelf_id=shelf.id,
        actor_user_id=admin.id,
        cells=[cell(product_id=product.id)],
    )
    activate_planogram(db, planogram_id=plan.id, actor_user_id=admin.id, reason="approved")
    db.query(models.ShelfProduct).filter_by(shelf_id=shelf.id, product_id=product.id).delete()
    db.flush()

    with pytest.raises(ShelfPlanogramError, match="active and assigned"):
        load_active_planogram_for_shelf(db, shelf_id=shelf.id, actor_user_id=admin.id)
