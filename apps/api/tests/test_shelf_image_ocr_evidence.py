import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
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


@pytest.fixture(autouse=True)
def isolated_database():
    previous_override = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    Base.metadata.drop_all(bind=TEST_ENGINE)


def create_image_with_detection():
    db = TestingSession()
    suffix = db.query(models.ShelfImage).count() + 1
    store = models.Store(code=f"OCR-{suffix:02d}", name="Loja OCR")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="S-01")
    db.add(shelf)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="shelf.jpg",
        storage_path=f"/tmp/ocr-shelf-{suffix}.jpg",
        mime_type="image/jpeg",
        file_size_bytes=100,
        sha256="a" * 64,
        analysis_status="COMPLETED",
        model_version="detector-v1",
    )
    db.add(image)
    db.flush()
    detection = models.ShelfImageDetection(
        shelf_image_id=image.id,
        label="product",
        confidence=0.95,
        x_min=0.1,
        y_min=0.1,
        x_max=0.8,
        y_max=0.8,
        model_version="detector-v1",
    )
    db.add(detection)
    db.commit()
    result = (image.id, detection.id)
    db.close()
    return result


def test_ocr_run_and_region_evidence_are_persisted_with_provenance():
    image_id, detection_id = create_image_with_detection()
    with TestClient(app) as client:
        created = client.post(
            f"/api/v1/shelf-images/{image_id}/ocr-runs",
            json={
                "provider": "paddleocr",
                "model_version": "PP-OCRv5-pt",
                "regions": [
                    {
                        "detection_id": detection_id,
                        "text": "Leite Meio-Gordo 1 L",
                        "confidence": 0.93,
                        "x_min": 0.2,
                        "y_min": 0.2,
                        "x_max": 0.6,
                        "y_max": 0.3,
                    },
                    {
                        "detection_id": None,
                        "text": "PROMOÇÃO",
                        "confidence": 0.72,
                        "x_min": 0.01,
                        "y_min": 0.01,
                        "x_max": 0.1,
                        "y_max": 0.05,
                    },
                ],
            },
        )
        assert created.status_code == 201
        assert created.json()["provider"] == "paddleocr"

        evidence = client.get(f"/api/v1/shelf-images/{image_id}/ocr-evidence")
        runs = client.get(f"/api/v1/shelf-images/{image_id}/ocr-runs")

        assert evidence.status_code == 200
        assert len(evidence.json()) == 2
        assigned = next(item for item in evidence.json() if item["detection_id"] is not None)
        assert assigned["detection_id"] == detection_id
        assert assigned["normalized_text"] == "leite meio gordo 1 l"
        assert assigned["association_status"] == "ASSIGNED"
        unassigned = next(item for item in evidence.json() if item["detection_id"] is None)
        assert unassigned["association_status"] == "UNASSIGNED"
        assert len(runs.json()) == 1
        assert runs.json()[0]["model_version"] == "PP-OCRv5-pt"


def test_ocr_run_rejects_detection_from_another_image():
    image_id, _ = create_image_with_detection()
    other_image_id, other_detection_id = create_image_with_detection()
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/shelf-images/{image_id}/ocr-runs",
            json={
                "provider": "paddleocr",
                "model_version": "PP-OCRv5-pt",
                "regions": [{
                    "detection_id": other_detection_id,
                    "text": "Produto",
                    "confidence": 0.9,
                    "x_min": 0.1,
                    "y_min": 0.1,
                    "x_max": 0.4,
                    "y_max": 0.4,
                }],
            },
        )
        assert response.status_code == 422


def test_ocr_run_rejects_text_without_alphanumeric_content():
    image_id, _ = create_image_with_detection()
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/shelf-images/{image_id}/ocr-runs",
            json={
                "provider": "paddleocr",
                "model_version": "PP-OCRv5-pt",
                "regions": [{
                    "text": "   !!! ",
                    "confidence": 0.9,
                    "x_min": 0.1,
                    "y_min": 0.1,
                    "x_max": 0.4,
                    "y_max": 0.4,
                }],
            },
        )
        assert response.status_code == 422
