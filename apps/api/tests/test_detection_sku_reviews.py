import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import models
from app.main import app

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


def setup_function():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    app.dependency_overrides[get_db] = override_get_db


def teardown_function():
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=TEST_ENGINE)


def create_detection(*, proposed_product_id=None, second_product=False):
    db = TestingSession()
    store = models.Store(code="REVIEW-01", name="Loja revisão")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="S-01")
    db.add(shelf)
    db.flush()
    first = models.Product(sku="SKU-REVIEW-1", name="Produto proposto", is_active=True)
    db.add(first)
    db.flush()
    second = None
    if second_product:
        second = models.Product(sku="SKU-REVIEW-2", name="Produto correto", is_active=True)
        db.add(second)
        db.flush()
    db.add(models.ShelfProduct(shelf_id=shelf.id, product_id=first.id, target_quantity=5))
    if second is not None:
        db.add(models.ShelfProduct(shelf_id=shelf.id, product_id=second.id, target_quantity=5))
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="shelf.jpg",
        storage_path="/tmp/review-shelf.jpg",
        mime_type="image/jpeg",
        file_size_bytes=100,
        sha256="d" * 64,
        analysis_status="COMPLETED",
        model_version="detector-v1",
    )
    db.add(image)
    db.flush()
    detection = models.ShelfImageDetection(
        shelf_image_id=image.id,
        product_id=proposed_product_id if proposed_product_id is not None else first.id,
        label="product",
        confidence=0.95,
        x_min=0.1,
        y_min=0.1,
        x_max=0.8,
        y_max=0.8,
        model_version="detector-v1",
        sku_match_status="MATCHED",
    )
    db.add(detection)
    db.commit()
    result = {
        "detection_id": detection.id,
        "proposed_product_id": first.id,
        "correct_product_id": second.id if second is not None else None,
        "image_id": image.id,
    }
    db.close()
    return result


def test_confirmed_detection_is_recorded_without_overwriting_model_result():
    data = create_detection()
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "CONFIRMED", "notes": "SKU confirmado na prateleira"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["decision"] == "CONFIRMED"
        assert body["previous_product_id"] == data["proposed_product_id"]
        assert body["selected_product_id"] == data["proposed_product_id"]

        db = TestingSession()
        detection = db.get(models.ShelfImageDetection, data["detection_id"])
        assert detection.product_id == data["proposed_product_id"]
        db.close()


def test_correction_and_rejection_are_appended_to_review_history():
    data = create_detection(second_product=True)
    with TestClient(app) as client:
        corrected = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "CORRECTED", "selected_product_id": data["correct_product_id"]},
        )
        rejected = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "REJECTED"},
        )
        history = client.get(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews"
        )

        assert corrected.status_code == 201
        assert corrected.json()["previous_product_id"] == data["proposed_product_id"]
        assert corrected.json()["selected_product_id"] == data["correct_product_id"]
        assert rejected.status_code == 201
        assert rejected.json()["selected_product_id"] is None
        assert [item["decision"] for item in history.json()] == ["CORRECTED", "REJECTED"]


def test_correction_requires_active_product_assigned_to_same_shelf():
    data = create_detection()
    db = TestingSession()
    other = models.Product(sku="SKU-OTHER", name="Produto não atribuído", is_active=True)
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "CORRECTED", "selected_product_id": other_id},
        )
        assert response.status_code == 422
