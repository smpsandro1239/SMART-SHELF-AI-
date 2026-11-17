import os
from types import SimpleNamespace

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module, models
from app.database import Base, get_db
from app.main import app

ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


def test_demo_detection_requires_human_review_and_is_idempotent(monkeypatch):
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    app.dependency_overrides[get_db] = override_get_db
    db = TestingSession()
    try:
        store = models.Store(code="DEMO-OBS-TEST", name="Demo observation test")
        db.add(store)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Demo zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code="DEMO-OBS-01")
        product = models.Product(sku="DEMO-OBS-SKU", name="Demo product")
        other_product = models.Product(sku="DEMO-OBS-OTHER", name="Other shelf product")
        reviewer = models.User(
            email="supervisor@demo-observation.test",
            full_name="Demo Supervisor",
            password_hash="not-used-in-this-test",
            role="SUPERVISOR",
            store_id=store.id,
            is_active=True,
        )
        db.add_all([shelf, product, other_product, reviewer])
        db.flush()
        db.add_all([
            models.ShelfProduct(shelf_id=shelf.id, product_id=product.id, target_quantity=8, min_display_quantity=2),
            models.ShelfProduct(shelf_id=shelf.id, product_id=other_product.id, target_quantity=8, min_display_quantity=2),
            models.InventorySnapshot(
                store_id=store.id, product_id=product.id, on_hand_quantity=12,
                reserved_quantity=0, source="MANUAL", external_reference="demo-observation-test-v1",
                captured_at=models.utc_now(),
            ),
        ])
        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="synthetic.png",
            storage_path="/tmp/synthetic.png",
            mime_type="image/png",
            file_size_bytes=128,
            sha256="a" * 64,
            analysis_status="COMPLETED",
            model_version="mock-shelf-vision-v1",
            retention_status="ACTIVE",
        )
        db.add(image)
        db.flush()
        detection = models.ShelfImageDetection(
            shelf_image_id=image.id,
            label="empty_facing",
            confidence=0.95,
            x_min=0.1,
            y_min=0.2,
            x_max=0.4,
            y_max=0.6,
            model_version="mock-shelf-vision-v1",
        )
        db.add(detection)
        db.commit()
        ids = (reviewer.id, store.id, product.id, other_product.id, detection.id)
    finally:
        db.close()

    reviewer_id, store_id, product_id, other_product_id, detection_id = ids
    monkeypatch.setattr(
        main_module,
        "_request_user",
        lambda db, request: SimpleNamespace(id=reviewer_id, role="SUPERVISOR", store_id=store_id),
    )

    with TestClient(app) as client:
        denied = client.post(
            f"/api/v1/shelf-image-detections/{detection_id}/observation",
            json={"product_id": product_id},
        )
        assert denied.status_code == 409
        assert "human SKU review" in denied.json()["detail"]

        db = TestingSession()
        try:
            db.add(models.DetectionSkuReview(
                detection_id=detection_id,
                selected_product_id=product_id,
                decision="CORRECTED",
                reviewer_user_id=reviewer_id,
                notes="SKU escolhido pelo supervisor para o cenário sintético.",
            ))
            db.commit()
        finally:
            db.close()

        first = client.post(
            f"/api/v1/shelf-image-detections/{detection_id}/observation",
            json={"product_id": product_id},
        )
        second = client.post(
            f"/api/v1/shelf-image-detections/{detection_id}/observation",
            json={"product_id": product_id},
        )
        decisions = client.get(f"/api/v1/operational-decisions?store_id={store_id}")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["status"] == "EMPTY"
    assert first.json()["observed_quantity"] == 0
    assert f"sha256={'a' * 64}" in first.json()["notes"]
    assert decisions.status_code == 200
    by_product = {row["product_id"]: row for row in decisions.json()["decisions"]}
    assert by_product[product_id]["replenishment_assessment"] is not None
    assert by_product[other_product_id]["replenishment_assessment"] is None

    db = TestingSession()
    try:
        assert db.query(models.Observation).filter(models.Observation.notes.like(f"%demo_detection_id={detection_id};%")).count() == 1
    finally:
        db.close()
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=ENGINE)



def test_store_employee_listing_is_role_and_store_scoped(monkeypatch):
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    app.dependency_overrides[get_db] = override_get_db
    db = TestingSession()
    try:
        store_a = models.Store(code="DEMO-EMP-A", name="Demo employee A")
        store_b = models.Store(code="DEMO-EMP-B", name="Demo employee B")
        db.add_all([store_a, store_b])
        db.flush()
        supervisor = models.User(
            email="supervisor@demo-employee.test", full_name="Supervisor A",
            password_hash="not-used", role="SUPERVISOR", store_id=store_a.id, is_active=True,
        )
        employee_a = models.User(
            email="employee-a@demo-employee.test", full_name="Employee A",
            password_hash="not-used", role="EMPLOYEE", store_id=store_a.id, is_active=True,
        )
        employee_b = models.User(
            email="employee-b@demo-employee.test", full_name="Employee B",
            password_hash="not-used", role="EMPLOYEE", store_id=store_b.id, is_active=True,
        )
        db.add_all([supervisor, employee_a, employee_b])
        db.commit()
        actor = {"value": SimpleNamespace(id=supervisor.id, role="SUPERVISOR", store_id=store_a.id)}
        store_a_id, store_b_id = store_a.id, store_b.id
        employee_a_id, employee_b_id = employee_a.id, employee_b.id
    finally:
        db.close()

    monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor["value"])
    try:
        with TestClient(app) as client:
            scoped = client.get("/api/v1/store-employees")
            assert scoped.status_code == 200
            assert [row["id"] for row in scoped.json()] == [employee_a_id]
            forbidden_store = client.get(f"/api/v1/store-employees?store_id={store_b_id}")
            assert forbidden_store.status_code == 403

            actor["value"] = SimpleNamespace(id=employee_a_id, role="EMPLOYEE", store_id=store_a_id)
            forbidden_role = client.get("/api/v1/store-employees")
            assert forbidden_role.status_code == 403

            actor["value"] = SimpleNamespace(id=999, role="ADMIN", store_id=None)
            admin_list = client.get("/api/v1/store-employees")
            assert admin_list.status_code == 200
            assert {row["id"] for row in admin_list.json()} == {employee_a_id, employee_b_id}
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=ENGINE)
