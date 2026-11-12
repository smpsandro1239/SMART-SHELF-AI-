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
from app import main as main_module

ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


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
