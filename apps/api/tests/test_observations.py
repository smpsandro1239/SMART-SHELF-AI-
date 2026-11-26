import os

import pytest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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


def test_observation_list_isolated_by_store_and_shelf_filter(monkeypatch):
    import app.main as main_module

    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        own_store = client.post(
            "/api/v1/stores",
            json={"code": "OBS-SCOPE-OWN", "name": "Loja própria"},
        )
        foreign_store = client.post(
            "/api/v1/stores",
            json={"code": "OBS-SCOPE-FOREIGN", "name": "Loja externa"},
        )
        assert own_store.status_code == foreign_store.status_code == 201

        shelves = {}
        for key, store in (("own", own_store), ("foreign", foreign_store)):
            zone = client.post(
                "/api/v1/zones",
                json={"store_id": store.json()["id"], "name": f"Zona {key}"},
            )
            shelf = client.post(
                "/api/v1/shelves",
                json={"zone_id": zone.json()["id"], "code": f"OBS-{key.upper()}"},
            )
            assert zone.status_code == shelf.status_code == 201
            shelves[key] = shelf.json()["id"]
            observation = client.post(
                "/api/v1/observations",
                json={
                    "shelf_id": shelves[key],
                    "source": "simulation",
                    "status": "LOW_STOCK" if key == "own" else "EMPTY",
                    "confidence": 0.9,
                },
            )
            assert observation.status_code == 201

        monkeypatch.setattr(
            main_module,
            "_request_user",
            lambda db, request: SimpleNamespace(
                id=7001,
                role="SUPERVISOR",
                store_id=own_store.json()["id"],
            ),
        )

        all_observations = client.get("/api/v1/observations")
        assert all_observations.status_code == 200
        assert len(all_observations.json()) == 1
        assert all_observations.json()[0]["shelf_id"] == shelves["own"]

        own_shelf = client.get(
            "/api/v1/observations",
            params={"shelf_id": shelves["own"]},
        )
        assert own_shelf.status_code == 200
        assert len(own_shelf.json()) == 1

        foreign_shelf = client.get(
            "/api/v1/observations",
            params={"shelf_id": shelves["foreign"]},
        )
        assert foreign_shelf.status_code == 200
        assert foreign_shelf.json() == []


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
    image_bytes = _valid_image_bytes()

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
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "IMG-04", "name": "Loja protegida"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Congelados"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "CG-01"})
        assert shelf.status_code == 201, shelf.text
        monkeypatch.setattr(
            main_module,
            "_request_user",
            lambda db, request: SimpleNamespace(id=44, role="SUPERVISOR", store_id=999),
        )
        response = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("capture.png", _valid_image_bytes(), "image/png")},
        )
        assert response.status_code == 404


def test_list_shelf_image_detections(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    image_bytes = _valid_image_bytes()

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
            files={"image": ("shelf.png", _valid_image_bytes(), "image/png")},
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
            files={"image": ("worker.png", _valid_image_bytes(), "image/png")},
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
            files={"image": ("worker.png", _valid_image_bytes(), "image/png")},
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
    actor = SimpleNamespace(id=77, role="ADMIN", store_id=None)
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)

    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "RETRY-01", "name": "Loja retry"})
        assert store.status_code == 201, store.text
        actor.store_id = store.json()["id"]
        zone = client.post("/api/v1/zones", json={"store_id": actor.store_id, "name": "Bebidas"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "RT-01"})
        actor.role = "SUPERVISOR"
        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf.json()["id"])},
            files={"image": ("retry.png", _valid_image_bytes(), "image/png")},
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


def test_shelf_observation_consensus_endpoint_uses_newest_observations():
    from datetime import datetime, timedelta, timezone

    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "CONS-01", "name": "Loja consenso"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Bebidas"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "CONS-01"})
        now = datetime.now(timezone.utc)

        # More than 500 old records must not hide the latest confirmations.
        db = TestingSession()
        try:
            db.add_all([
                models.Observation(
                    shelf_id=shelf.json()["id"],
                    source="fixed_camera",
                    status="LOW_STOCK",
                    confidence=0.95,
                    observed_at=now - timedelta(days=2, seconds=index),
                )
                for index in range(500)
            ])
            db.add_all([
                models.Observation(
                    shelf_id=shelf.json()["id"],
                    source="fixed_camera",
                    status="LOW_STOCK",
                    confidence=0.91,
                    observed_at=now - timedelta(seconds=seconds_ago),
                )
                for seconds_ago in (30, 15, 0)
            ])
            db.commit()
        finally:
            db.close()

        response = client.get(f"/api/v1/shelves/{shelf.json()['id']}/observation-consensus")
        assert response.status_code == 200
        body = response.json()
        assert body["evaluated_observations"] == 500
        assert body["consensus"]["status"] == "CONFIRMED"
        assert body["consensus"]["consensus_observation_status"] == "LOW_STOCK"
        assert body["consensus"]["confirmations"] == 3
        assert body["consensus"]["requires_human_approval"] is True
        assert body["consensus"]["automatic_task_creation_allowed"] is False
        assert body["consensus"]["automatic_stock_movement_allowed"] is False
        assert body["scope"] == "SHELF"
        assert body["sku_attribution_available"] is False

def test_shelf_observation_consensus_endpoint_enforces_store_scope(monkeypatch):
    from types import SimpleNamespace
    import app.main as main_module

    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "CONS-02", "name": "Loja privada"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Frescos"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "CONS-02"})
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: SimpleNamespace(id=91, role="SUPERVISOR", store_id=999))
        response = client.get(f"/api/v1/shelves/{shelf.json()['id']}/observation-consensus")
        assert response.status_code == 404




def test_shelf_observation_consensus_rechecks_tenant_on_evidence_query(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    import app.main as main_module

    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store_a = client.post("/api/v1/stores", json={"code": "CONS-RACE-A", "name": "Loja A"}).json()
        store_b = client.post("/api/v1/stores", json={"code": "CONS-RACE-B", "name": "Loja B"}).json()
        zone = client.post(
            "/api/v1/zones",
            json={"store_id": store_a["id"], "name": "Zona A"},
        ).json()
        shelf = client.post(
            "/api/v1/shelves",
            json={"zone_id": zone["id"], "code": "CONS-RACE-SHELF"},
        ).json()
        observation = client.post(
            "/api/v1/observations",
            json={
                "shelf_id": shelf["id"],
                "source": "simulation",
                "status": "LOW_STOCK",
                "confidence": 0.95,
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert observation.status_code == 201, observation.text

        monkeypatch.setattr(
            main_module,
            "_request_user",
            lambda db, request: SimpleNamespace(id=91, role="SUPERVISOR", store_id=store_a["id"]),
        )
        original_scope = main_module._get_store_scoped_shelf

        def reassign_after_preflight(db, shelf_id, actor):
            scoped_shelf = original_scope(db, shelf_id, actor)
            db.query(models.Zone).filter(models.Zone.id == zone["id"]).update(
                {models.Zone.store_id: store_b["id"]},
                synchronize_session=False,
            )
            db.commit()
            return scoped_shelf

        monkeypatch.setattr(main_module, "_get_store_scoped_shelf", reassign_after_preflight)
        response = client.get(f"/api/v1/shelves/{shelf['id']}/observation-consensus")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["store_id"] == store_a["id"]
        assert body["evaluated_observations"] == 0
        assert body["consensus"]["status"] != "CONFIRMED"


def test_observation_product_must_be_assigned_to_shelf():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "OBS-SKU-01", "name": "Loja SKU"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Bebidas"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "SKU-01"})
        product = client.post("/api/v1/products", json={"sku": "SKU-OBS-01", "name": "Produto de teste"})
        assert product.status_code == 201

        rejected = client.post(
            "/api/v1/observations",
            json={
                "shelf_id": shelf.json()["id"],
                "product_id": product.json()["id"],
                "source": "simulation",
                "status": "LOW_STOCK",
                "confidence": 0.9,
            },
        )
        assert rejected.status_code == 422

        assigned = client.post(
            "/api/v1/shelf-products",
            json={"shelf_id": shelf.json()["id"], "product_id": product.json()["id"]},
        )
        assert assigned.status_code == 201

        accepted = client.post(
            "/api/v1/observations",
            json={
                "shelf_id": shelf.json()["id"],
                "product_id": product.json()["id"],
                "source": "simulation",
                "status": "LOW_STOCK",
                "confidence": 0.9,
            },
        )
        assert accepted.status_code == 201
        assert accepted.json()["product_id"] == product.json()["id"]


def test_observation_consensus_is_isolated_per_sku_and_legacy_evidence():
    from datetime import datetime, timedelta, timezone

    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    with TestClient(app) as client:
        store = client.post("/api/v1/stores", json={"code": "OBS-SKU-02", "name": "Loja consenso SKU"})
        zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Frescos"})
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "SKU-CONS-01"})
        assert shelf.status_code == 201, shelf.text
        shelf_id = shelf.json()["id"]
        product_a = client.post("/api/v1/products", json={"sku": "SKU-CONS-A", "name": "Produto A"}).json()
        product_b = client.post("/api/v1/products", json={"sku": "SKU-CONS-B", "name": "Produto B"}).json()
        for product in (product_a, product_b):
            assigned = client.post(
                "/api/v1/shelf-products",
                json={"shelf_id": shelf_id, "product_id": product["id"]},
            )
            assert assigned.status_code == 201

        now = datetime.now(timezone.utc)
        for product, status in ((product_a, "LOW_STOCK"), (product_b, "EMPTY")):
            for seconds_ago in (40, 20):
                observed_at = (now - timedelta(seconds=seconds_ago)).isoformat()
                response = client.post(
                    "/api/v1/observations",
                    json={
                        "shelf_id": shelf_id,
                        "product_id": product["id"],
                        "source": "simulation",
                        "status": status,
                        "confidence": 0.95,
                        "observed_at": observed_at,
                    },
                )
                assert response.status_code == 201

        common = {
            "minimum_confirmations": 2,
            "minimum_interval_seconds": 5,
            "minimum_confidence": 0.6,
        }
        consensus_a = client.get(
            f"/api/v1/shelves/{shelf_id}/observation-consensus",
            params={**common, "product_id": product_a["id"]},
        )
        consensus_b = client.get(
            f"/api/v1/shelves/{shelf_id}/observation-consensus",
            params={**common, "product_id": product_b["id"]},
        )
        legacy = client.get(
            f"/api/v1/shelves/{shelf_id}/observation-consensus",
            params=common,
        )

        assert consensus_a.status_code == consensus_b.status_code == legacy.status_code == 200
        assert consensus_a.json()["scope"] == "SHELF_SKU"
        assert consensus_a.json()["sku_attribution_available"] is True
        assert consensus_a.json()["consensus"]["consensus_observation_status"] == "LOW_STOCK"
        assert consensus_b.json()["consensus"]["consensus_observation_status"] == "EMPTY"
        assert legacy.json()["scope"] == "SHELF"
        assert legacy.json()["sku_attribution_available"] is False
        assert legacy.json()["consensus"]["status"] == "NO_CONSENSUS"



def _setup_alert_fixture(client):
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    store = client.post("/api/v1/stores", json={"code": "ALERT-STORE", "name": "Loja alertas"})
    assert store.status_code == 201, store.text
    zone = client.post("/api/v1/zones", json={"store_id": store.json()["id"], "name": "Bebidas"})
    assert zone.status_code == 201, zone.text
    shelf = client.post("/api/v1/shelves", json={"zone_id": zone.json()["id"], "code": "ALERT-SHELF"})
    assert shelf.status_code == 201, shelf.text
    product = client.post("/api/v1/products", json={"sku": "ALERT-SKU", "name": "Produto alerta"})
    assert product.status_code == 201, product.text
    assignment = client.post(
        "/api/v1/shelf-products",
        json={"shelf_id": shelf.json()["id"], "product_id": product.json()["id"]},
    )
    assert assignment.status_code == 201, assignment.text
    now = datetime.now(timezone.utc)
    for seconds_ago in (60, 40, 20):
        observation = client.post(
            "/api/v1/observations",
            json={
                "shelf_id": shelf.json()["id"],
                "product_id": product.json()["id"],
                "source": "simulation",
                "status": "LOW_STOCK",
                "confidence": 0.95,
                "observed_at": (now - timedelta(seconds=seconds_ago)).isoformat(),
            },
        )
        assert observation.status_code == 201, observation.text

    db = TestingSession()
    user = models.User(
        email="supervisor-alert@example.test",
        store_id=store.json()["id"],
        full_name="Supervisor Alertas",
        password_hash="test-hash",
        role="SUPERVISOR",
        is_active=True,
    )
    db.add(user)
    db.commit()
    actor = SimpleNamespace(id=user.id, role=user.role, store_id=user.store_id)
    ids = (store.json()["id"], shelf.json()["id"], product.json()["id"])
    db.close()
    return ids, actor


def test_observation_alert_is_idempotent_and_human_resolvable(monkeypatch):
    import app.main as main_module

    with TestClient(app) as client:
        (store_id, shelf_id, product_id), actor = _setup_alert_fixture(client)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)
        params = {
            "product_id": product_id,
            "minimum_confirmations": 3,
            "minimum_interval_seconds": 10,
            "minimum_confidence": 0.6,
        }
        first = client.post(f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate", params=params)
        assert first.status_code == 200, first.text
        second = client.post(f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate", params=params)
        assert second.status_code == 200, second.text
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["status"] == "OPEN"

        repeated_events = client.get(f"/api/v1/observation-alerts/{first.json()['id']}/events")
        assert repeated_events.status_code == 200
        assert [event["event_type"] for event in repeated_events.json()] == ["CREATED"]

        listed = client.get("/api/v1/observation-alerts", params={"status": "OPEN"})
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        missing_reason = client.patch(
            f"/api/v1/observation-alerts/{first.json()['id']}",
            json={"status": "RESOLVED", "reason": "   "},
        )
        assert missing_reason.status_code == 422

        acknowledged = client.patch(
            f"/api/v1/observation-alerts/{first.json()['id']}",
            json={"status": "ACKNOWLEDGED"},
        )
        assert acknowledged.status_code == 200
        assert acknowledged.json()["status"] == "ACKNOWLEDGED"

        resolved = client.patch(
            f"/api/v1/observation-alerts/{first.json()['id']}",
            json={"status": "RESOLVED", "reason": "Prateleira verificada e reposta"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "RESOLVED"
        assert resolved.json()["resolution_reason"] == "Prateleira verificada e reposta"

        events = client.get(f"/api/v1/observation-alerts/{first.json()['id']}/events")
        assert events.status_code == 200
        assert [event["event_type"] for event in events.json()] == [
            "CREATED", "ACKNOWLEDGED", "RESOLVED"
        ]

        reopened = client.post(f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate", params=params)
        assert reopened.status_code == 200, reopened.text
        assert reopened.json()["id"] != first.json()["id"]
        assert reopened.json()["status"] == "OPEN"


def test_observation_alerts_are_store_scoped(monkeypatch):
    import app.main as main_module

    with TestClient(app) as client:
        (store_id, shelf_id, product_id), actor = _setup_alert_fixture(client)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)

        created = client.post(
            f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate",
            params={"product_id": product_id, "minimum_confirmations": 3},
        )
        assert created.status_code == 200, created.text
        assert created.json() is not None

        own_store_alerts = client.get("/api/v1/observation-alerts")
        assert own_store_alerts.status_code == 200
        assert [alert["id"] for alert in own_store_alerts.json()] == [created.json()["id"]]

        foreign_actor = SimpleNamespace(
            id=actor.id, role="SUPERVISOR", store_id=store_id + 999
        )
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: foreign_actor)
        foreign_store_alerts = client.get("/api/v1/observation-alerts")
        assert foreign_store_alerts.status_code == 200
        assert foreign_store_alerts.json() == []
        filtered_foreign_alerts = client.get(
            "/api/v1/observation-alerts",
            params={"shelf_id": shelf_id, "product_id": product_id},
        )
        assert filtered_foreign_alerts.status_code == 200
        assert filtered_foreign_alerts.json() == []

        evaluate = client.post(
            f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate",
            params={"product_id": product_id, "minimum_confirmations": 3},
        )
        assert evaluate.status_code == 404

        employee_actor = SimpleNamespace(
            id=actor.id, role="EMPLOYEE", store_id=store_id
        )
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: employee_actor)
        employee_alerts = client.get("/api/v1/observation-alerts")
        assert employee_alerts.status_code == 403

        admin_actor = SimpleNamespace(id=actor.id, role="ADMIN", store_id=None)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: admin_actor)
        admin_alerts = client.get("/api/v1/observation-alerts")
        assert admin_alerts.status_code == 200
        assert [alert["id"] for alert in admin_alerts.json()] == [created.json()["id"]]

def test_cross_store_alert_update_checks_scope_before_acquiring_row_lock(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    import app.main as main_module

    alert = SimpleNamespace(id=41, store_id=22, status="OPEN")
    lock_attempts = []

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def with_for_update(self):
            lock_attempts.append(True)
            return self

        def populate_existing(self):
            return self

        def first(self):
            return alert

    class FakeSession:
        def query(self, model):
            return Query()

    foreign_supervisor = SimpleNamespace(id=7, role="SUPERVISOR", store_id=11)
    monkeypatch.setattr(
        main_module,
        "_request_user",
        lambda db, request: foreign_supervisor,
    )

    with pytest.raises(HTTPException) as error:
        main_module.update_observation_alert(
            41,
            SimpleNamespace(status="ACKNOWLEDGED", reason=None),
            SimpleNamespace(),
            FakeSession(),
        )

    assert error.value.status_code == 404
    assert lock_attempts == []
    assert alert.status == "OPEN"

def test_cross_store_alert_event_history_is_denied(monkeypatch):
    import app.main as main_module

    with TestClient(app) as client:
        (store_id, shelf_id, product_id), actor = _setup_alert_fixture(client)
        monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor)

        created = client.post(
            f"/api/v1/shelves/{shelf_id}/observation-alerts/evaluate",
            params={"product_id": product_id, "minimum_confirmations": 3},
        )
        assert created.status_code == 200, created.text
        assert created.json() is not None
        alert_id = created.json()["id"]
        history_url = f"/api/v1/observation-alerts/{alert_id}/events"

        # A supervisor must retain access to the history of their own store.
        own_store_history = client.get(history_url)
        assert own_store_history.status_code == 200, own_store_history.text
        assert [event["event_type"] for event in own_store_history.json()] == ["CREATED"]

        foreign_actor = SimpleNamespace(
            id=actor.id, role="SUPERVISOR", store_id=store_id + 999
        )
        monkeypatch.setattr(
            main_module, "_request_user", lambda db, request: foreign_actor
        )
        foreign_store_history = client.get(history_url)
        missing_history = client.get(
            "/api/v1/observation-alerts/2147483000/events"
        )
        assert foreign_store_history.status_code == missing_history.status_code == 404
        assert foreign_store_history.json() == missing_history.json()

        # EMPLOYEE is not allowed to inspect alert history, even in another store.
        employee_actor = SimpleNamespace(
            id=actor.id, role="EMPLOYEE", store_id=store_id
        )
        monkeypatch.setattr(
            main_module, "_request_user", lambda db, request: employee_actor
        )
        employee_history = client.get(history_url)
        assert employee_history.status_code == 403

        # ADMIN has global visibility and may inspect the same history.
        admin_actor = SimpleNamespace(
            id=actor.id, role="ADMIN", store_id=None
        )
        monkeypatch.setattr(
            main_module, "_request_user", lambda db, request: admin_actor
        )
        admin_history = client.get(history_url)
        assert admin_history.status_code == 200, admin_history.text
        assert [event["event_type"] for event in admin_history.json()] == ["CREATED"]


def test_shelf_write_endpoints_lock_and_revalidate_store_scope(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.config import settings
    import app.main as main_module

    monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)

    with TestClient(app) as client:
        store_a = client.post(
            "/api/v1/stores", json={"code": "SHELF-LOCK-A", "name": "Loja A"}
        ).json()
        store_b = client.post(
            "/api/v1/stores", json={"code": "SHELF-LOCK-B", "name": "Loja B"}
        ).json()
        zone_a = client.post(
            "/api/v1/zones", json={"store_id": store_a["id"], "name": "Zona A"}
        ).json()
        zone_b = client.post(
            "/api/v1/zones", json={"store_id": store_b["id"], "name": "Zona B"}
        ).json()
        shelf_a = client.post(
            "/api/v1/shelves", json={"zone_id": zone_a["id"], "code": "LOCK-A"}
        ).json()
        shelf_a_other = client.post(
            "/api/v1/shelves", json={"zone_id": zone_a["id"], "code": "LOCK-A2"}
        ).json()
        shelf_b = client.post(
            "/api/v1/shelves", json={"zone_id": zone_b["id"], "code": "LOCK-B"}
        ).json()

        foreign_session = client.post(
            "/api/v1/capture-sessions",
            json={"shelf_id": shelf_b["id"], "source_type": "MOBILE"},
        )
        assert foreign_session.status_code == 201, foreign_session.text

        monkeypatch.setattr(
            main_module,
            "_request_user",
            lambda db, request: SimpleNamespace(
                id=501, role="SUPERVISOR", store_id=store_a["id"]
            ),
        )

        observation_foreign = client.post(
            "/api/v1/observations",
            json={
                "shelf_id": shelf_b["id"],
                "source": "manual",
                "status": "LOW_STOCK",
                "confidence": 0.9,
            },
        )
        assert observation_foreign.status_code == 404

        session_foreign = client.post(
            "/api/v1/capture-sessions",
            json={"shelf_id": shelf_b["id"], "source_type": "MOBILE"},
        )
        assert session_foreign.status_code == 404

        session_own = client.post(
            "/api/v1/capture-sessions",
            json={"shelf_id": shelf_a["id"], "source_type": "MOBILE"},
        )
        assert session_own.status_code == 201, session_own.text

        upload_foreign_shelf = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf_b["id"])},
            files={"image": ("foreign.png", _valid_image_bytes(), "image/png")},
        )
        assert upload_foreign_shelf.status_code == 404

        upload_foreign_session = client.post(
            "/api/v1/shelf-images",
            data={
                "shelf_id": str(shelf_a["id"]),
                "capture_session_id": str(foreign_session.json()["id"]),
            },
            files={"image": ("foreign-session.png", _valid_image_bytes(), "image/png")},
        )
        assert upload_foreign_session.status_code == 404

        upload_mismatched_session = client.post(
            "/api/v1/shelf-images",
            data={
                "shelf_id": str(shelf_a_other["id"]),
                "capture_session_id": str(session_own.json()["id"]),
            },
            files={"image": ("mismatched.png", _valid_image_bytes(), "image/png")},
        )
        assert upload_mismatched_session.status_code == 422

        upload_own = client.post(
            "/api/v1/shelf-images",
            data={
                "shelf_id": str(shelf_a["id"]),
                "capture_session_id": str(session_own.json()["id"]),
            },
            files={"image": ("own.png", _valid_image_bytes(), "image/png")},
        )
        assert upload_own.status_code == 201, upload_own.text

        db = TestingSession()
        try:
            assert db.query(models.Observation).filter_by(shelf_id=shelf_b["id"]).count() == 0
            assert db.query(models.ShelfImage).filter_by(shelf_id=shelf_b["id"]).count() == 0
            assert db.query(models.ShelfImage).filter_by(shelf_id=shelf_a_other["id"]).count() == 0
        finally:
            db.close()
