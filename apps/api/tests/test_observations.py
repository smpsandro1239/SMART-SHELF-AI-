import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from io import BytesIO
from PIL import Image

from app.database import Base, get_db
from app import models  # noqa: F401
from app.main import app

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=TEST_ENGINE)


def _valid_image_bytes(image_format="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color=(20, 80, 140)).save(buffer, format=image_format)
    return buffer.getvalue()


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


def test_create_store_shelf_and_observation():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "TEST-01", "name": "Loja de teste"})
        assert store.status_code == 201
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Bebidas"})
        assert zone.status_code == 201
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "BEB-01"})
        assert shelf.status_code == 201
        observation = client.post(
            "/api/v1/observations",
            json={"shelf_id": shelf.json()["id"], "source": "simulation", "status": "LOW_STOCK", "confidence": 0.82},
        )
        assert observation.status_code == 201
        assert observation.json()["status"] == "LOW_STOCK"
        listed = client.get("/api/v1/observations", params={"shelf_id": shelf.json()["id"]})
        assert listed.status_code == 200
        assert len(listed.json()) == 1


def test_observation_rejects_confidence_outside_range():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/observations",
            json={"shelf_id": 1, "confidence": 1.5},
        )
        assert response.status_code == 422


def test_upload_and_retrieve_shelf_image(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"test-image-payload"

    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "IMG-01", "name": "Loja imagem"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Frescos"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "FR-01"})
        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("shelf.png", image_bytes, "image/png")},
        )
        assert uploaded.status_code == 201
        record = uploaded.json()
        assert record["analysis_status"] == "PENDING"
        assert record["mime_type"] == "image/png"
        assert record["file_size_bytes"] == len(image_bytes)
        assert len(record["sha256"]) == 64

        listed = client.get("/api/v1/shelf-images", params={"shelf_id": shelf.json()["id"]})
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        content = client.get(f"/api/v1/shelf-images/{record['id']}/content")
        assert content.status_code == 200
        assert content.content == image_bytes


def test_upload_rejects_mismatched_image_signature(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "IMG-02", "name": "Loja imagem 2"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Bebidas"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "BE-01"})
        response = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("not-image.png", b"not a real PNG", "image/png")},
        )
        assert response.status_code == 415


def test_upload_rejects_unsupported_media_type():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "IMG-03", "name": "Loja imagem 3"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Laticínios"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "LA-01"})
        response = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("capture.gif", b"GIF89a", "image/gif")},
        )
        assert response.status_code == 415


def test_supervisor_cannot_upload_image_to_another_store(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.config import settings
    import app.main as main_module

    monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
    monkeypatch.setattr(
        main_module,
        "_request_user",
        lambda db, request: SimpleNamespace(id=44, role="SUPERVISOR", store_id=999),
    )
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "IMG-04", "name": "Loja protegida"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Congelados"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "CG-01"})
        response = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("capture.png", b"\x89PNG\r\n\x1a\nvalid-signature", "image/png")},
        )
        assert response.status_code == 403


def test_list_shelf_image_detections(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    image_bytes = b"\x89PNG\r\n\x1a\n" + b"test-image-payload"

    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "DET-01", "name": "Loja deteções"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Bebidas"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "DET-01"})
        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("shelf.png", image_bytes, "image/png")},
        )
        assert uploaded.status_code == 201
        image_id = uploaded.json()["id"]

        db = TestingSession()
        try:
            detection = models.ShelfImageDetection(
                shelf_image_id=image_id,
                label="bottle",
                confidence=0.94,
                x_min=0.1,
                y_min=0.2,
                x_max=0.6,
                y_max=0.9,
                model_version="test-model-0.1",
            )
            db.add(detection)
            db.commit()
        finally:
            db.close()

        response = client.get(f"/api/v1/shelf-images/{image_id}/detections")
        assert response.status_code == 200
        records = response.json()
        assert len(records) == 1
        assert records[0]["label"] == "bottle"
        assert records[0]["confidence"] == 0.94
        assert records[0]["model_version"] == "test-model-0.1"
        assert records[0]["x_min"] == 0.1
        assert records[0]["x_max"] == 0.6


def test_detection_query_respects_store_scope(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.config import settings
    import app.main as main_module

    monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "DET-02", "name": "Loja privada"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Frescos"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "FR-02"})
        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("shelf.png", b"\x89PNG\r\n\x1a\nvalid-signature", "image/png")},
        )
        assert uploaded.status_code == 201
        monkeypatch.setattr(
            main_module,
            "_request_user",
            lambda db, request: SimpleNamespace(id=99, role="SUPERVISOR", store_id=999),
        )
        response = client.get(f"/api/v1/shelf-images/{uploaded.json()['id']}/detections")
        assert response.status_code == 403


def test_vision_worker_persists_provider_detections(tmp_path, monkeypatch):
    from app.config import settings
    from app.vision import VisionAnalysis
    from app.vision_worker import process_next_image

    monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)

    class FakeProvider:
        def analyze(self, image_path):
            assert image_path.is_file()
            return VisionAnalysis.model_validate({
                "model_version": "fake-test-1",
                "detections": [{
                    "label": "water_bottle",
                    "confidence": 0.97,
                    "x_min": 0.1,
                    "y_min": 0.2,
                    "x_max": 0.7,
                    "y_max": 0.9,
                }],
            })

    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "WORK-01", "name": "Worker test"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Bebidas"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "WK-01"})
        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("worker.png", b"\x89PNG\r\n\x1a\nworker-test", "image/png")},
        )
        assert uploaded.status_code == 201
        image_id = uploaded.json()["id"]

        db = TestingSession()
        try:
            assert process_next_image(db, FakeProvider()) == image_id
            image = db.get(models.ShelfImage, image_id)
            assert image.analysis_status == "COMPLETED"
            assert image.model_version == "fake-test-1"
            assert image.analysis_started_at is not None
            assert image.analysis_completed_at is not None
            assert image.analysis_error is None
            detections = db.query(models.ShelfImageDetection).filter_by(shelf_image_id=image_id).all()
            assert len(detections) == 1
            assert detections[0].label == "water_bottle"
            assert detections[0].confidence == 0.97
        finally:
            db.close()


def test_vision_worker_marks_provider_errors_as_failed(tmp_path, monkeypatch):
    from app.config import settings
    from app.vision_worker import process_next_image

    monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)

    class BrokenProvider:
        def analyze(self, image_path):
            raise RuntimeError("provider unavailable")

    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "WORK-02", "name": "Worker failure"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Frescos"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "WK-02"})
        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("worker.png", b"\x89PNG\r\n\x1a\nworker-test", "image/png")},
        )
        assert uploaded.status_code == 201
        image_id = uploaded.json()["id"]

        db = TestingSession()
        try:
            assert process_next_image(db, BrokenProvider()) == image_id
            image = db.get(models.ShelfImage, image_id)
            assert image.analysis_status == "FAILED"
            assert image.analysis_error == "RuntimeError: processing failed"
            assert image.analysis_completed_at is not None
            assert db.query(models.ShelfImageDetection).filter_by(shelf_image_id=image_id).count() == 0
        finally:
            db.close()


def test_failed_image_analysis_can_be_retried_by_store_supervisor(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.config import settings
    import app.main as main_module

    monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
    actor = SimpleNamespace(id=77, role="SUPERVISOR", store_id=None)
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)

    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "RETRY-01", "name": "Loja retry"})
        actor.store_id = store.json()["id"]
        zone = client.post("/api/v1/zones", json={"store_id": actor.store_id, "name": "Bebidas"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "RT-01"})
        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("retry.png", b"\x89PNG\r\n\x1a\nretry-test", "image/png")},
        )
        assert uploaded.status_code == 201
        image_id = uploaded.json()["id"]

        db = TestingSession()
        try:
            image = db.get(models.ShelfImage, image_id)
            image.analysis_status = "FAILED"
            image.analysis_error = "RuntimeError: processing failed"
            image.model_version = "old-model"
            image.analysis_started_at = models.utc_now()
            image.analysis_completed_at = models.utc_now()
            db.commit()
        finally:
            db.close()

        retried = client.post(f"/api/v1/shelf-images/{image_id}/retry")
        assert retried.status_code == 200
        assert retried.json()["analysis_status"] == "PENDING"
        assert retried.json()["analysis_error"] is None
        assert retried.json()["analysis_started_at"] is None
        assert retried.json()["analysis_completed_at"] is None
        assert retried.json()["model_version"] is None

        conflict = client.post(f"/api/v1/shelf-images/{image_id}/retry")
        assert conflict.status_code == 409

        db = TestingSession()
        try:
            image = db.get(models.ShelfImage, image_id)
            image.analysis_status = "FAILED"
            db.commit()
        finally:
            db.close()

        actor.store_id = 999
        forbidden = client.post(f"/api/v1/shelf-images/{image_id}/retry")
        assert forbidden.status_code == 403
