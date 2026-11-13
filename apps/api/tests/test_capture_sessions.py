import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from io import BytesIO
from PIL import Image

from app.database import Base, get_db
from app import models
from app.main import app
from app import main as main_module

ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


def _valid_image_bytes(image_format="JPEG"):
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color=(20, 80, 140)).save(buffer, format=image_format)
    return buffer.getvalue()


def override_get_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_database():
    previous = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous
    Base.metadata.drop_all(bind=ENGINE)


def seed_shelves():
    db = Session()
    store = models.Store(code="CAP-01", name="Capture test store")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Aisle 1")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="A1-01")
    other_shelf = models.Shelf(zone_id=zone.id, code="A1-02")
    db.add_all([shelf, other_shelf])
    db.commit()
    result = (shelf.id, other_shelf.id)
    db.close()
    return result


def test_capture_session_create_list_and_close():
    shelf_id, _ = seed_shelves()
    with TestClient(app) as client:
        created = client.post("/api/v1/capture-sessions", json={
            "shelf_id": shelf_id,
            "source_type": "mobile",
            "source_device_id": "device-pseudonym-01",
            "capture_mode": "burst",
        })
        assert created.status_code == 201
        session = created.json()
        assert session["shelf_id"] == shelf_id
        assert session["source_type"] == "mobile"
        assert session["ended_at"] is None

        listed = client.get("/api/v1/capture-sessions", params={"shelf_id": shelf_id, "include_closed": False})
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [session["id"]]

        closed = client.post(f"/api/v1/capture-sessions/{session['id']}/close")
        assert closed.status_code == 200
        assert closed.json()["ended_at"] is not None

        closed_again = client.post(f"/api/v1/capture-sessions/{session['id']}/close")
        assert closed_again.status_code == 200
        assert closed_again.json()["ended_at"] == closed.json()["ended_at"]


def test_session_cannot_be_attached_to_another_shelf(tmp_path, monkeypatch):
    shelf_id, other_shelf_id = seed_shelves()
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    with TestClient(app) as client:
        created = client.post("/api/v1/capture-sessions", json={
            "shelf_id": shelf_id,
            "source_type": "fixed_camera",
            "capture_mode": "single",
        })
        assert created.status_code == 201
        session_id = created.json()["id"]

        response = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(other_shelf_id), "capture_session_id": str(session_id)},
            files={"image": ("shelf.jpg", b"\xff\xd8\xff" + b"x" * 20, "image/jpeg")},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "Capture session does not belong to this shelf"


def test_upload_links_image_to_open_capture_session(tmp_path, monkeypatch):
    shelf_id, _ = seed_shelves()
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    with TestClient(app) as client:
        created = client.post("/api/v1/capture-sessions", json={
            "shelf_id": shelf_id,
            "source_type": "robot",
            "source_device_id": "robot-pseudonym-02",
            "capture_mode": "video_sample",
        })
        assert created.status_code == 201
        session_id = created.json()["id"]

        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf_id), "capture_session_id": str(session_id)},
            files={"image": ("frame.jpg", b"\xff\xd8\xff" + b"frame-data", "image/jpeg")},
        )
        assert uploaded.status_code == 201
        assert uploaded.json()["capture_session_id"] == session_id

        closed = client.post(f"/api/v1/capture-sessions/{session_id}/close")
        assert closed.status_code == 200
        rejected = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf_id), "capture_session_id": str(session_id)},
            files={"image": ("late-frame.jpg", b"\xff\xd8\xff" + b"frame-data", "image/jpeg")},
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"] == "Capture session is closed"


def test_reviewed_training_candidates_group_by_capture_session():
    shelf_id, _ = seed_shelves()
    db = Session()
    store_id = db.query(models.Zone.store_id).join(models.Shelf, models.Shelf.zone_id == models.Zone.id).filter(models.Shelf.id == shelf_id).scalar()
    session = models.CaptureSession(
        store_id=store_id, shelf_id=shelf_id, source_type="mobile",
        capture_mode="burst", started_at=models.utc_now(),
    )
    db.add(session)
    db.flush()
    product = models.Product(sku="CAP-SKU-1", name="Capture product", is_active=True)
    db.add(product)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf_id, capture_session_id=session.id,
        original_filename="frame.jpg", storage_path="/tmp/capture-session-frame.jpg",
        mime_type="image/jpeg", file_size_bytes=100, sha256="f" * 64,
    )
    db.add(image)
    db.flush()
    detection = models.ShelfImageDetection(
        shelf_image_id=image.id, product_id=product.id, label="product",
        confidence=0.95, x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
        model_version="detector-v1", sku_match_status="MATCHED",
    )
    db.add(detection)
    db.flush()
    db.add(models.DetectionSkuReview(
        detection_id=detection.id, previous_product_id=product.id,
        selected_product_id=product.id, decision="CONFIRMED",
    ))
    db.commit()
    session_id = session.id
    db.close()

    with TestClient(app) as client:
        response = client.get("/api/v1/training-candidates/reviewed")
    assert response.status_code == 200
    candidate = response.json()[0]
    assert candidate["capture_session_id"] == session_id
    assert candidate["capture_group_key"] == f"session:{session_id}"
    assert "same capture session" in candidate["split_policy"]
