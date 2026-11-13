import os
from pathlib import Path

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
from app.security import create_access_token

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

def test_review_queue_returns_unreviewed_conflicts_and_removes_reviewed_items(monkeypatch):
    image_id, detection_id = create_image_with_detection()
    db = TestingSession()
    image = db.get(models.ShelfImage, image_id)
    shelf = db.get(models.Shelf, image.shelf_id)
    zone = db.get(models.Zone, shelf.zone_id)
    supervisor = models.User(
        email="supervisor-queue@test.local",
        full_name="Supervisor Queue",
        password_hash="test-hash",
        role="SUPERVISOR",
        store_id=zone.store_id,
        is_active=True,
    )
    db.add(supervisor)
    run = models.ShelfImageOCRRun(
        shelf_image_id=image.id, provider="mock-ocr", model_version="mock-v1", status="COMPLETED"
    )
    db.add(run)
    db.flush()
    db.add(models.ShelfImageFusedEvidence(
        ocr_run_id=run.id,
        detection_id=detection_id,
        status="CONFLICT",
        suggested_product_id=None,
        visual_product_id=None,
        text_product_id=None,
        visual_status="MATCHED",
        text_status="SUGGESTED",
        visual_similarity=0.9,
        text_score=0.91,
        ocr_confidence=0.95,
        visual_model_version="visual-v1",
        ocr_provider="mock-ocr",
        ocr_model_version="mock-v1",
        reason="conflict needs review",
    ))
    db.commit()
    supervisor_id = supervisor.id
    db.close()

    monkeypatch.setattr(main_module, "SessionLocal", TestingSession)
    token, _ = create_access_token(user_id=supervisor_id, role="SUPERVISOR")
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        summary = client.get("/api/v1/shelf-image-review-queue/summary", headers=headers)
        assert summary.status_code == 200
        assert summary.json()["CONFLICT"] == 1

        queue = client.get("/api/v1/shelf-image-review-queue", headers=headers)
        assert queue.status_code == 200
        assert len(queue.json()) == 1
        assert queue.json()[0]["status"] == "CONFLICT"
        assert queue.json()[0]["detection_id"] == detection_id

        reviewed = client.post(
            f"/api/v1/shelf-image-detections/{detection_id}/reviews",
            headers=headers,
            json={"decision": "REJECTED", "selected_product_id": None, "notes": "OCR/visual conflict rejected"},
        )
        assert reviewed.status_code == 201
        assert reviewed.json()["decision"] == "REJECTED"

        queue_after_review = client.get("/api/v1/shelf-image-review-queue", headers=headers)
        assert queue_after_review.status_code == 200
        assert queue_after_review.json() == []
        summary_after_review = client.get("/api/v1/shelf-image-review-queue/summary", headers=headers)
        assert summary_after_review.status_code == 200
        assert summary_after_review.json()["CONFLICT"] == 0



def test_image_detection_and_ocr_endpoints_enforce_store_scope(monkeypatch):
    own_image_id, own_detection_id = create_image_with_detection()
    foreign_image_id, foreign_detection_id = create_image_with_detection()

    with TestingSession() as db:
        own_image = db.get(models.ShelfImage, own_image_id)
        own_shelf = db.get(models.Shelf, own_image.shelf_id)
        own_zone = db.get(models.Zone, own_shelf.zone_id)
        actor = models.User(
            email="image-scope-supervisor@example.test",
            full_name="Supervisor da loja de origem",
            password_hash="test-only-not-used",
            role="SUPERVISOR",
            store_id=own_zone.store_id,
            is_active=True,
        )
        db.add(actor)
        db.commit()
        db.refresh(actor)
        actor_id = actor.id

    with TestClient(app) as client:
        own_run = client.post(
            f"/api/v1/shelf-images/{own_image_id}/ocr-runs",
            json={
                "provider": "mock-ocr",
                "model_version": "mock-v1",
                "regions": [{
                    "detection_id": own_detection_id,
                    "text": "Produto próprio",
                    "confidence": 0.95,
                    "x_min": 0.1,
                    "y_min": 0.1,
                    "x_max": 0.6,
                    "y_max": 0.3,
                }],
            },
        )
        assert own_run.status_code == 201

        with TestingSession() as db:
            actor = db.get(models.User, actor_id)
            monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

            own_detections = client.get(f"/api/v1/shelf-images/{own_image_id}/detections")
            own_runs = client.get(f"/api/v1/shelf-images/{own_image_id}/ocr-runs")
            own_evidence = client.get(f"/api/v1/shelf-images/{own_image_id}/ocr-evidence")
            assert own_detections.status_code == 200
            assert len(own_detections.json()) == 1
            assert own_runs.status_code == 200
            assert len(own_runs.json()) == 1
            assert own_evidence.status_code == 200
            assert len(own_evidence.json()) == 1

            foreign_detections = client.get(f"/api/v1/shelf-images/{foreign_image_id}/detections")
            foreign_runs = client.get(f"/api/v1/shelf-images/{foreign_image_id}/ocr-runs")
            foreign_evidence = client.get(f"/api/v1/shelf-images/{foreign_image_id}/ocr-evidence")
            assert foreign_detections.status_code == 403
            assert foreign_runs.status_code == 403
            assert foreign_evidence.status_code == 403

            foreign_ocr_create = client.post(
                f"/api/v1/shelf-images/{foreign_image_id}/ocr-runs",
                json={
                    "provider": "mock-ocr",
                    "model_version": "mock-v1",
                    "regions": [{
                        "detection_id": foreign_detection_id,
                        "text": "Tentativa externa",
                        "confidence": 0.9,
                        "x_min": 0.1,
                        "y_min": 0.1,
                        "x_max": 0.5,
                        "y_max": 0.3,
                    }],
                },
            )
            assert foreign_ocr_create.status_code == 403

            foreign_review = client.post(
                f"/api/v1/shelf-image-detections/{foreign_detection_id}/reviews",
                json={"decision": "REJECTED", "notes": "Tentativa cross-store"},
            )
            assert foreign_review.status_code == 403



def test_image_content_endpoint_enforces_store_scope_and_file_availability(monkeypatch, tmp_path):
    from types import SimpleNamespace

    own_image_id, _ = create_image_with_detection()
    foreign_image_id, _ = create_image_with_detection()

    db = TestingSession()
    own_image = db.get(models.ShelfImage, own_image_id)
    foreign_image = db.get(models.ShelfImage, foreign_image_id)
    own_shelf = db.get(models.Shelf, own_image.shelf_id)
    own_zone = db.get(models.Zone, own_shelf.zone_id)
    foreign_shelf = db.get(models.Shelf, foreign_image.shelf_id)
    foreign_zone = db.get(models.Zone, foreign_shelf.zone_id)
    own_store_id = own_zone.store_id
    foreign_store_id = foreign_zone.store_id
    storage_root = tmp_path / "storage"
    own_dir = storage_root / str(own_store_id)
    foreign_dir = storage_root / str(foreign_store_id)
    own_dir.mkdir(parents=True)
    foreign_dir.mkdir(parents=True)
    own_file = own_dir / "own-image.jpg"
    foreign_file = foreign_dir / "foreign-image.jpg"
    own_file.write_bytes(b"own-image-content")
    foreign_file.write_bytes(b"foreign-image-content")
    own_image.storage_path = str(own_file)
    foreign_image.storage_path = str(foreign_file)
    db.commit()
    db.close()

    monkeypatch.setattr(main_module.settings, "image_storage_path", str(storage_root))
    supervisor = SimpleNamespace(role="SUPERVISOR", store_id=own_store_id)
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: supervisor)

    with TestClient(app) as client:
        own_response = client.get(f"/api/v1/shelf-images/{own_image_id}/content")
        assert own_response.status_code == 200
        assert own_response.content == b"own-image-content"

        foreign_response = client.get(f"/api/v1/shelf-images/{foreign_image_id}/content")
        assert foreign_response.status_code == 403

        missing_image = client.get("/api/v1/shelf-images/99999/content")
        assert missing_image.status_code == 404

        db = TestingSession()
        own_image = db.get(models.ShelfImage, own_image_id)
        own_image.storage_path = str(own_dir / "deleted-file.jpg")
        db.commit()
        db.close()

        missing_file = client.get(f"/api/v1/shelf-images/{own_image_id}/content")
        assert missing_file.status_code == 404



def test_shelf_image_upload_decodes_content_and_sanitizes_filename(monkeypatch, tmp_path):
    from hashlib import sha256
    from io import BytesIO
    from PIL import Image

    db = TestingSession()
    store = models.Store(code="UPLOAD-HARDEN", name="Loja upload")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona upload")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="UPLOAD-01")
    db.add(shelf)
    db.commit()
    shelf_id, store_id = shelf.id, store.id
    db.close()

    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    output = BytesIO()
    Image.new("RGB", (16, 12), (30, 80, 120)).save(output, format="PNG")
    valid_png = output.getvalue()

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf_id)},
            files={"image": ("..\\..\\outside.png", valid_png, "image/png")},
        )
        assert uploaded.status_code == 201
        record = uploaded.json()
        assert record["original_filename"] == "outside.png"
        assert record["mime_type"] == "image/png"
        assert record["file_size_bytes"] == len(valid_png)
        assert record["sha256"] == sha256(valid_png).hexdigest()

        db = TestingSession()
        stored_record = db.get(models.ShelfImage, record["id"])
        actual_path = Path(stored_record.storage_path)
        db.close()
        assert actual_path.parent == tmp_path / str(store_id)
        assert actual_path.read_bytes() == valid_png
        assert not (tmp_path / "outside.png").exists()

        spoofed = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf_id)},
            files={"image": ("spoof.png", b"\x89PNG\r\n\x1a\nnot-a-real-png", "image/png")},
        )
        assert spoofed.status_code == 415

        mismatched = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf_id)},
            files={"image": ("wrong.jpg", valid_png, "image/jpeg")},
        )
        assert mismatched.status_code == 415


def test_shelf_image_upload_rejects_payload_over_configured_limit(monkeypatch, tmp_path):
    from io import BytesIO
    from PIL import Image

    db = TestingSession()
    store = models.Store(code="UPLOAD-LIMIT", name="Loja limite")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona limite")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="LIMIT-01")
    db.add(shelf)
    db.commit()
    shelf_id = shelf.id
    db.close()

    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    monkeypatch.setattr(main_module.settings, "max_image_upload_bytes", 1024)
    output = BytesIO()
    Image.effect_noise((128, 128), 100).convert("RGB").save(output, format="PNG")
    payload = output.getvalue()
    assert len(payload) > 1024

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf_id)},
            files={"image": ("large.png", payload, "image/png")},
        )
    assert response.status_code == 413
    assert not list(tmp_path.rglob("*"))


def test_shelf_image_content_rejects_paths_outside_store_and_symlinks(monkeypatch, tmp_path):
    db = TestingSession()
    store = models.Store(code="IMAGE-PATH-GUARD", name="Loja path guard")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona path guard")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="PATH-01")
    db.add(shelf)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="private.jpg",
        storage_path=str(tmp_path / "outside.jpg"),
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256="b" * 64,
        analysis_status="COMPLETED",
    )
    db.add(image)
    db.commit()
    image_id, store_id = image.id, store.id
    db.close()

    storage_root = tmp_path / "storage"
    store_dir = storage_root / str(store_id)
    store_dir.mkdir(parents=True)
    outside_file = tmp_path / "outside.jpg"
    outside_file.write_bytes(b"outside-data")
    linked_file = store_dir / "linked.jpg"
    try:
        linked_file.symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are not supported by this test environment")

    monkeypatch.setattr(main_module.settings, "image_storage_path", str(storage_root))
    supervisor = type("Supervisor", (), {"role": "SUPERVISOR", "store_id": store_id})()
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: supervisor)

    db = TestingSession()
    db.get(models.ShelfImage, image_id).storage_path = str(outside_file)
    db.commit()
    db.close()
    with TestClient(app) as client:
        traversal = client.get(f"/api/v1/shelf-images/{image_id}/content")
        assert traversal.status_code == 404

    db = TestingSession()
    db.get(models.ShelfImage, image_id).storage_path = str(linked_file)
    db.commit()
    db.close()
    with TestClient(app) as client:
        symlink = client.get(f"/api/v1/shelf-images/{image_id}/content")
        assert symlink.status_code == 404



def test_shelf_image_retention_metadata_defaults_to_active_and_is_exposed():
    image_id, _ = create_image_with_detection()

    db = TestingSession()
    image = db.get(models.ShelfImage, image_id)
    assert image.retention_status == "ACTIVE"
    assert image.legal_hold is False
    assert image.retention_requested_at is None
    assert image.purge_not_before is None
    assert image.purged_at is None
    db.close()

    with TestClient(app) as client:
        response = client.get("/api/v1/shelf-images")
    assert response.status_code == 200
    record = next(item for item in response.json() if item["id"] == image_id)
    assert record["retention_status"] == "ACTIVE"
    assert record["legal_hold"] is False
    assert record["retention_policy_version"] is None



def test_retention_restriction_blocks_image_access_and_is_audited(monkeypatch, tmp_path):
    image_id, _ = create_image_with_detection()
    db = TestingSession()
    image = db.get(models.ShelfImage, image_id)
    shelf = db.get(models.Shelf, image.shelf_id)
    zone = db.get(models.Zone, shelf.zone_id)
    supervisor = models.User(
        email="retention-supervisor@test.local", full_name="Retention Supervisor",
        password_hash="test-hash", role="SUPERVISOR", store_id=zone.store_id, is_active=True,
    )
    admin = models.User(
        email="retention-admin@test.local", full_name="Retention Admin",
        password_hash="test-hash", role="ADMIN", store_id=None, is_active=True,
    )
    db.add_all([supervisor, admin])
    db.commit()
    supervisor_id, admin_id, store_id = supervisor.id, admin.id, zone.store_id
    image_path = tmp_path / str(store_id) / "shelf.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"test-image")
    image.storage_path = str(image_path)
    db.commit()
    db.close()

    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    actor = {"user": None}
    def select_actor(user_id):
        session = TestingSession()
        actor["user"] = session.get(models.User, user_id)
        session.expunge(actor["user"])
        session.close()
    select_actor(supervisor_id)
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor["user"])

    with TestClient(app) as client:
        restricted = client.post(
            f"/api/v1/shelf-images/{image_id}/retention/restrict",
            json={"reason": "Pedido de privacidade"},
        )
        assert restricted.status_code == 200
        assert restricted.json()["retention_status"] == "RESTRICTED"
        assert client.get(f"/api/v1/shelf-images/{image_id}/content").status_code == 410
        assert client.get(f"/api/v1/shelf-images/{image_id}/detections").status_code == 410
        assert client.get(f"/api/v1/shelf-images/{image_id}/ocr-runs").status_code == 410
        listing = client.get("/api/v1/shelf-images")
        assert listing.status_code == 200
        assert all(row["id"] != image_id for row in listing.json())
        events = client.get(f"/api/v1/shelf-images/{image_id}/retention/events")
        assert events.status_code == 200
        assert [event["event_type"] for event in events.json()] == ["RESTRICTED"]

        assert client.post(
            f"/api/v1/shelf-images/{image_id}/retention/restore",
            json={"reason": "Revisão concluída"},
        ).status_code == 403

        select_actor(admin_id)
        restored = client.post(
            f"/api/v1/shelf-images/{image_id}/retention/restore",
            json={"reason": "Revisão concluída"},
        )
        assert restored.status_code == 200
        assert restored.json()["retention_status"] == "ACTIVE"
        events = client.get(f"/api/v1/shelf-images/{image_id}/retention/events")
        assert [event["event_type"] for event in events.json()] == ["RESTRICTED", "RESTORED"]
