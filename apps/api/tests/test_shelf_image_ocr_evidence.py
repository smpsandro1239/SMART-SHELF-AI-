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


def test_cached_ocr_matches_are_reranked_when_catalogue_product_is_deactivated():
    image_id, detection_id = create_image_with_detection()
    with TestingSession() as db:
        product = models.Product(sku="OCR-CACHE-01", name="Leite Meio Gordo", is_active=True)
        db.add(product)
        db.flush()
        product_id = product.id
        run = models.ShelfImageOCRRun(
            shelf_image_id=image_id,
            provider="mock-ocr",
            model_version="mock-v1",
            status="COMPLETED",
        )
        db.add(run)
        db.flush()
        db.add(models.ShelfImageOCRMatch(
            run_id=run.id,
            detection_id=detection_id,
            suggested_product_id=product_id,
            observed_text="Leite Meio Gordo",
            ocr_confidence=0.98,
            status="SUGGESTED",
            top_score=1.0,
            margin=0.5,
            candidates=[{"product_id": product_id, "score": 1.0, "reasons": ["name"]}],
        ))
        db.commit()
        run_id = run.id

    with TestClient(app) as client:
        initial = client.get(f"/api/v1/shelf-images/{image_id}/ocr-matches")
        assert initial.status_code == 200
        assert initial.json()[0]["suggested_product_id"] == product_id

        with TestingSession() as db:
            product = db.get(models.Product, product_id)
            product.is_active = False
            db.commit()

        listed = client.get(f"/api/v1/shelf-images/{image_id}/ocr-matches")
        repeated = client.post(f"/api/v1/shelf-images/{image_id}/ocr-matches")
        assert listed.status_code == 200
        assert repeated.status_code == 200
        for response in (listed, repeated):
            result = response.json()[0]
            assert result["suggested_product_id"] is None
            assert result["status"] == "UNKNOWN"
            assert result["top_score"] is None
            assert result["candidates"] == []

    with TestingSession() as db:
        # Historical inference remains immutable; only the served view is refreshed.
        stored = db.query(models.ShelfImageOCRMatch).filter_by(run_id=run_id).one()
        assert stored.suggested_product_id == product_id
        assert stored.candidates[0]["product_id"] == product_id



def test_cached_fused_evidence_is_recomputed_when_catalogue_product_is_deactivated():
    image_id, detection_id = create_image_with_detection()
    with TestingSession() as db:
        product = models.Product(sku="FUSION-CACHE-01", name="Produto Fusion", is_active=True)
        db.add(product)
        db.flush()
        product_id = product.id
        detection = db.get(models.ShelfImageDetection, detection_id)
        detection.sku_match_status = "MATCHED"
        detection.product_id = product_id
        detection.sku_similarity = 0.96
        detection.sku_match_margin = 0.12
        run = models.ShelfImageOCRRun(
            shelf_image_id=image_id, provider="mock-ocr", model_version="mock-v1", status="COMPLETED"
        )
        db.add(run)
        db.flush()
        db.add(models.ShelfImageOCRMatch(
            run_id=run.id, detection_id=detection_id, suggested_product_id=product_id,
            observed_text="Produto Fusion", ocr_confidence=0.98, status="SUGGESTED",
            top_score=1.0, margin=0.5,
            candidates=[{"product_id": product_id, "score": 1.0, "reasons": ["name"]}],
        ))
        db.commit()
        run_id = run.id
        fused = models.ShelfImageFusedEvidence(
            ocr_run_id=run_id, detection_id=detection_id, status=
            "CONSENSUS", suggested_product_id=product_id, visual_product_id=product_id,
            text_product_id=product_id, visual_status=
            "MATCHED", text_status="SUGGESTED", visual_similarity=0.96,
            text_score=1.0, ocr_confidence=0.98, visual_model_version=
            "visual-v1", ocr_provider="mock-ocr", ocr_model_version="mock-v1",
            reason="historical consensus",
        )
        db.add(fused)
        db.commit()

    with TestClient(app) as client:
        initial = client.get(f"/api/v1/shelf-images/{image_id}/evidence-fusion")
        assert initial.status_code == 200
        assert initial.json()[0]["status"] == "CONSENSUS"
        assert initial.json()[0]["suggested_product_id"] == product_id

        with TestingSession() as db:
            db.get(models.Product, product_id).is_active = False
            db.commit()

        listed = client.get(f"/api/v1/shelf-images/{image_id}/evidence-fusion")
        cached = client.post(f"/api/v1/shelf-images/{image_id}/evidence-fusion")
        stale_status_filter = client.get(
            f"/api/v1/shelf-images/{image_id}/evidence-fusion?status=CONSENSUS"
        )
        assert listed.status_code == 200
        assert cached.status_code == 200
        assert stale_status_filter.status_code == 200
        assert stale_status_filter.json() == []
        for response in (listed, cached):
            result = response.json()[0]
            assert result["status"] == "UNKNOWN"
            assert result["suggested_product_id"] is None
            assert result["visual_product_id"] is None
            assert result["text_product_id"] is None
            assert result["visual_status"] == "UNKNOWN"
            assert result["text_status"] == "UNKNOWN"

    with TestingSession() as db:
        stored = db.query(models.ShelfImageFusedEvidence).filter_by(
            ocr_run_id=run_id, detection_id=detection_id
        ).one()
        assert stored.status == "CONSENSUS"
        assert stored.suggested_product_id == product_id
        assert stored.visual_product_id == product_id
        assert stored.text_product_id == product_id

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


def test_review_queue_revalidates_fused_products_after_catalogue_deactivation():
    image_id, detection_id = create_image_with_detection()
    with TestingSession() as db:
        product = models.Product(sku="QUEUE-FUSION-01", name="Produto Queue", is_active=True)
        db.add(product)
        db.flush()
        product_id = product.id
        run = models.ShelfImageOCRRun(
            shelf_image_id=image_id, provider="queue-ocr", model_version="queue-v1", status="COMPLETED"
        )
        db.add(run)
        db.flush()
        db.add(models.ShelfImageFusedEvidence(
            ocr_run_id=run.id, detection_id=detection_id, status="CONSENSUS",
            suggested_product_id=product_id, visual_product_id=product_id,
            text_product_id=product_id, visual_status="MATCHED", text_status="SUGGESTED",
            visual_similarity=0.96, text_score=1.0, ocr_confidence=0.98,
            visual_model_version="visual-v1", ocr_provider="queue-ocr",
            ocr_model_version="queue-v1", reason="historical consensus",
        ))
        db.commit()

    with TestClient(app) as client:
        initial = client.get("/api/v1/shelf-image-review-queue")
        assert initial.status_code == 200
        assert initial.json()[0]["status"] == "CONSENSUS"
        fused_id = initial.json()[0]["fused_evidence_id"]

        with TestingSession() as db:
            db.get(models.Product, product_id).is_active = False
            db.commit()

        refreshed = client.get("/api/v1/shelf-image-review-queue")
        filtered = client.get("/api/v1/shelf-image-review-queue?status=CONSENSUS")
        assert refreshed.status_code == 200
        assert filtered.status_code == 200
        assert filtered.json() == []
        item = next(item for item in refreshed.json() if item["fused_evidence_id"] == fused_id)
        assert item["status"] == "UNKNOWN"
        assert item["suggested_product_id"] is None
        assert item["visual_product_id"] is None
        assert item["text_product_id"] is None

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
    visual_product = models.Product(
        sku="QUEUE-VISUAL-01", name="Visual candidate", is_active=True,
    )
    text_product = models.Product(
        sku="QUEUE-TEXT-01", name="Text candidate", is_active=True,
    )
    db.add_all([visual_product, text_product])
    db.flush()
    db.add(models.ShelfImageFusedEvidence(
        ocr_run_id=run.id,
        detection_id=detection_id,
        status="CONFLICT",
        suggested_product_id=None,
        visual_product_id=visual_product.id,
        text_product_id=text_product.id,
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

            # A rejected cross-store request must not append OCR or review rows.
            before_rejected_writes = (
                db.query(models.ShelfImageOCRRun).count(),
                db.query(models.ShelfImageOCREvidence).count(),
                db.query(models.DetectionSkuReview).count(),
            )

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
            assert foreign_review.status_code == 404

            db.expire_all()
            after_rejected_writes = (
                db.query(models.ShelfImageOCRRun).count(),
                db.query(models.ShelfImageOCREvidence).count(),
                db.query(models.DetectionSkuReview).count(),
            )
            assert after_rejected_writes == before_rejected_writes



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
    own_content = b"own-image-content"
    foreign_content = b"foreign-image-content"
    own_file.write_bytes(own_content)
    foreign_file.write_bytes(foreign_content)
    own_image.storage_path = str(own_file)
    own_image.file_size_bytes = len(own_content)
    own_image.sha256 = __import__("hashlib").sha256(own_content).hexdigest()
    foreign_image.storage_path = str(foreign_file)
    foreign_image.file_size_bytes = len(foreign_content)
    foreign_image.sha256 = __import__("hashlib").sha256(foreign_content).hexdigest()
    db.commit()
    db.close()

    monkeypatch.setattr(main_module.settings, "image_storage_path", str(storage_root))
    supervisor = SimpleNamespace(role="SUPERVISOR", store_id=own_store_id)
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: supervisor)

    with TestClient(app) as client:
        own_response = client.get(f"/api/v1/shelf-images/{own_image_id}/content")
        assert own_response.status_code == 200
        assert own_response.content == b"own-image-content"

        # A file replaced after upload must not be served as trusted content.
        tampered_file = own_dir / "tampered-image.jpg"
        tampered_file.write_bytes(b"tampered-content")
        db = TestingSession()
        own_image = db.get(models.ShelfImage, own_image_id)
        own_image.storage_path = str(tampered_file)
        db.commit()
        db.close()
        tampered_response = client.get(f"/api/v1/shelf-images/{own_image_id}/content")
        assert tampered_response.status_code == 409

        # Restore the valid file metadata before continuing the path checks.
        db = TestingSession()
        own_image = db.get(models.ShelfImage, own_image_id)
        own_image.storage_path = str(own_file)
        db.commit()
        db.close()

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
    image_id, detection_id = create_image_with_detection()
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
        assert client.get(
            f"/api/v1/shelf-image-detections/{detection_id}/reviews"
        ).status_code == 410
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


def test_legal_hold_requires_admin_and_records_append_only_events(monkeypatch):
    image_id, _ = create_image_with_detection()
    with TestingSession() as db:
        image = db.get(models.ShelfImage, image_id)
        shelf = db.get(models.Shelf, image.shelf_id)
        zone = db.get(models.Zone, shelf.zone_id)
        admin = models.User(
            email="retention-admin@example.test",
            full_name="Retention Admin",
            password_hash="test-only-not-used",
            role="ADMIN",
            store_id=zone.store_id,
            is_active=True,
        )
        supervisor = models.User(
            email="retention-supervisor@example.test",
            full_name="Retention Supervisor",
            password_hash="test-only-not-used",
            role="SUPERVISOR",
            store_id=zone.store_id,
            is_active=True,
        )
        db.add_all([admin, supervisor])
        db.commit()
        db.refresh(admin)
        db.refresh(supervisor)
        admin_id, supervisor_id = admin.id, supervisor.id

    with TestClient(app) as client:
        with TestingSession() as db:
            supervisor = db.get(models.User, supervisor_id)
            monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: supervisor)
            denied = client.post(
                f"/api/v1/shelf-images/{image_id}/retention/legal-hold/apply",
                json={"reason": "Legal review requested"},
            )
            assert denied.status_code == 403

        with TestingSession() as db:
            admin = db.get(models.User, admin_id)
            monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: admin)
            blank_reason = client.post(
                f"/api/v1/shelf-images/{image_id}/retention/legal-hold/apply",
                json={"reason": "   "},
            )
            assert blank_reason.status_code == 422

            applied = client.post(
                f"/api/v1/shelf-images/{image_id}/retention/legal-hold/apply",
                json={"reason": "  Preservar evidência para análise jurídica  "},
            )
            assert applied.status_code == 200
            assert applied.json()["legal_hold"] is True
            assert applied.json()["retention_status"] == "ACTIVE"
            assert applied.json()["retention_reason"] is None
            events_after_apply = client.get(f"/api/v1/shelf-images/{image_id}/retention/events")
            assert events_after_apply.json()[0]["reason"] == "Preservar evidência para análise jurídica"

            repeated = client.post(
                f"/api/v1/shelf-images/{image_id}/retention/legal-hold/apply",
                json={"reason": "Pedido repetido"},
            )
            assert repeated.status_code == 200

            released = client.post(
                f"/api/v1/shelf-images/{image_id}/retention/legal-hold/release",
                json={"reason": "Análise jurídica concluída"},
            )
            assert released.status_code == 200
            assert released.json()["legal_hold"] is False

            events = client.get(f"/api/v1/shelf-images/{image_id}/retention/events")
            assert events.status_code == 200
            assert [event["event_type"] for event in events.json()] == [
                "LEGAL_HOLD_APPLIED", "LEGAL_HOLD_RELEASED"
            ]
            assert all(event["from_status"] == "ACTIVE" and event["to_status"] == "ACTIVE"
                       for event in events.json())



def test_cross_store_restricted_image_returns_forbidden_before_retention_state(monkeypatch):
    own_image_id, _ = create_image_with_detection()
    foreign_image_id, foreign_detection_id = create_image_with_detection()
    with TestingSession() as db:
        own_image = db.get(models.ShelfImage, own_image_id)
        own_shelf = db.get(models.Shelf, own_image.shelf_id)
        own_zone = db.get(models.Zone, own_shelf.zone_id)
        foreign_image = db.get(models.ShelfImage, foreign_image_id)
        foreign_image.retention_status = "RESTRICTED"
        actor = models.User(
            email="retention-scope-supervisor@example.test",
            full_name="Store Supervisor",
            password_hash="test-only-not-used",
            role="SUPERVISOR",
            store_id=own_zone.store_id,
            is_active=True,
        )
        foreign_image.retention_status = "RESTRICTED"
        db.add(actor)
        db.commit()
        db.refresh(actor)
        actor_id = actor.id

    with TestingSession() as db:
        actor = db.get(models.User, actor_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
        with TestClient(app) as client:
            paths = [
                f"/api/v1/shelf-images/{foreign_image_id}/content",
                f"/api/v1/shelf-images/{foreign_image_id}/detections",
                f"/api/v1/shelf-images/{foreign_image_id}/ocr-runs",
                f"/api/v1/shelf-images/{foreign_image_id}/ocr-evidence",
                f"/api/v1/shelf-images/{foreign_image_id}/ocr-matches",
                f"/api/v1/shelf-images/{foreign_image_id}/evidence-fusion",
                f"/api/v1/shelf-image-detections/{foreign_detection_id}/reviews",
            ]
            for path in paths:
                response = client.get(path)
                expected_status = 404 if path.endswith(f"/shelf-image-detections/{foreign_detection_id}/reviews") else 403
                assert response.status_code == expected_status, (path, response.status_code, response.text)



def test_retention_event_history_enforces_cross_store_scope(monkeypatch):
    own_image_id, _ = create_image_with_detection()
    foreign_image_id, _ = create_image_with_detection()
    with TestingSession() as db:
        own_image = db.get(models.ShelfImage, own_image_id)
        own_shelf = db.get(models.Shelf, own_image.shelf_id)
        own_zone = db.get(models.Zone, own_shelf.zone_id)
        foreign_image = db.get(models.ShelfImage, foreign_image_id)
        foreign_image.retention_status = "RESTRICTED"
        actor = models.User(
            email="retention-events-scope@example.test",
            full_name="Retention Events Supervisor",
            password_hash="test-only-not-used",
            role="SUPERVISOR",
            store_id=own_zone.store_id,
            is_active=True,
        )
        employee = models.User(
            email="retention-events-employee@example.test",
            full_name="Retention Events Employee",
            password_hash="test-only-not-used",
            role="EMPLOYEE",
            store_id=own_zone.store_id,
            is_active=True,
        )
        db.add_all([actor, employee])
        db.add(models.ShelfImageRetentionEvent(
            shelf_image_id=foreign_image_id,
            event_type="RESTRICTED",
            from_status="ACTIVE",
            to_status="RESTRICTED",
            reason="Sensitive retention reason from another store",
        ))
        db.commit()
        db.refresh(actor)
        db.refresh(employee)
        actor_id, employee_id = actor.id, employee.id

    with TestingSession() as db:
        actor = db.get(models.User, actor_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
        with TestClient(app) as client:
            own_events = client.get(
                f"/api/v1/shelf-images/{own_image_id}/retention/events"
            )
            assert own_events.status_code == 200
            assert own_events.json() == []

            employee = db.get(models.User, employee_id)
            monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: employee)
            employee_events = client.get(
                f"/api/v1/shelf-images/{own_image_id}/retention/events"
            )
            assert employee_events.status_code == 403

            monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
            foreign_events = client.get(
                f"/api/v1/shelf-images/{foreign_image_id}/retention/events"
            )
            assert foreign_events.status_code == 404
            assert "Sensitive retention reason" not in foreign_events.text

def test_cross_store_supervisor_cannot_mutate_foreign_shelf_image(monkeypatch):
    own_image_id, _ = create_image_with_detection()
    foreign_image_id, foreign_detection_id = create_image_with_detection()

    with TestingSession() as db:
        own_image = db.get(models.ShelfImage, own_image_id)
        own_shelf = db.get(models.Shelf, own_image.shelf_id)
        own_zone = db.get(models.Zone, own_shelf.zone_id)
        foreign_image = db.get(models.ShelfImage, foreign_image_id)
        foreign_image.analysis_status = "FAILED"
        actor = models.User(
            email="cross-store-image-writer@example.test",
            full_name="Store Supervisor",
            password_hash="test-only-not-used",
            role="SUPERVISOR",
            store_id=own_zone.store_id,
            is_active=True,
        )
        db.add(actor)
        db.commit()
        db.refresh(actor)
        actor_id = actor.id

    with TestingSession() as db:
        actor = db.get(models.User, actor_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

        with TestClient(app) as client:
            attempts = [
                (
                    "POST",
                    f"/api/v1/shelf-images/{foreign_image_id}/ocr-runs",
                    {
                        "provider": "mock-ocr",
                        "model_version": "mock-v1",
                        "regions": [],
                    },
                ),
                (
                    "POST",
                    f"/api/v1/shelf-images/{foreign_image_id}/evidence-fusion",
                    None,
                ),
                (
                    "POST",
                    f"/api/v1/shelf-image-detections/{foreign_detection_id}/reviews",
                    {
                        "decision": "REJECTED",
                        "selected_product_id": None,
                        "notes": "Cross-store authorization regression test",
                    },
                ),
                (
                    "POST",
                    f"/api/v1/shelf-images/{foreign_image_id}/retry",
                    None,
                ),
                (
                    "POST",
                    f"/api/v1/shelf-images/{foreign_image_id}/retention/restrict",
                    {"reason": "Cross-store authorization regression test"},
                ),
            ]

            for method, path, payload in attempts:
                response = client.request(method, path, json=payload)
                expected_status = 404 if path.endswith(f"/shelf-image-detections/{foreign_detection_id}/reviews") else 403
                assert response.status_code == expected_status, (
                    method,
                    path,
                    response.status_code,
                    response.text,
                )

    with TestingSession() as db:
        foreign_image = db.get(models.ShelfImage, foreign_image_id)
        assert foreign_image.retention_status == "ACTIVE"
        assert foreign_image.analysis_status == "FAILED"
        assert db.query(models.ShelfImageOCRRun).filter(
            models.ShelfImageOCRRun.shelf_image_id == foreign_image_id
        ).count() == 0
        assert db.query(models.DetectionSkuReview).filter(
            models.DetectionSkuReview.detection_id == foreign_detection_id
        ).count() == 0

def test_restricted_image_is_removed_from_review_queue_and_summary(monkeypatch):
    image_id, detection_id = create_image_with_detection()
    with TestingSession() as db:
        image = db.get(models.ShelfImage, image_id)
        shelf = db.get(models.Shelf, image.shelf_id)
        zone = db.get(models.Zone, shelf.zone_id)
        supervisor = models.User(
            email="supervisor-retention-queue@test.local",
            full_name="Supervisor Retention Queue",
            password_hash="test-hash",
            role="SUPERVISOR",
            store_id=zone.store_id,
            is_active=True,
        )
        db.add(supervisor)
        run = models.ShelfImageOCRRun(
            shelf_image_id=image_id,
            provider="mock-ocr",
            model_version="mock-v1",
            status="COMPLETED",
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
            reason="restricted queue regression",
        ))
        db.commit()
        supervisor_id = supervisor.id

    monkeypatch.setattr(main_module, "SessionLocal", TestingSession)
    token, _ = create_access_token(user_id=supervisor_id, role="SUPERVISOR")
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        before_summary = client.get(
            "/api/v1/shelf-image-review-queue/summary",
            headers=headers,
        )
        before_queue = client.get("/api/v1/shelf-image-review-queue", headers=headers)
        assert before_summary.status_code == 200
        assert before_summary.json()["CONFLICT"] == 1
        assert before_queue.status_code == 200
        assert [item["detection_id"] for item in before_queue.json()] == [detection_id]

        restricted = client.post(
            f"/api/v1/shelf-images/{image_id}/retention/restrict",
            headers=headers,
            json={"reason": "Imagem retirada da fila por retenção"},
        )
        assert restricted.status_code == 200
        assert restricted.json()["retention_status"] == "RESTRICTED"

        after_summary = client.get(
            "/api/v1/shelf-image-review-queue/summary",
            headers=headers,
        )
        after_queue = client.get("/api/v1/shelf-image-review-queue", headers=headers)
        assert after_summary.status_code == 200
        assert after_summary.json()["CONFLICT"] == 0
        assert after_queue.status_code == 200
        assert after_queue.json() == []




def test_supervisor_cannot_upload_image_to_foreign_store_shelf(monkeypatch, tmp_path):
    from io import BytesIO
    from types import SimpleNamespace
    from PIL import Image

    own_image_id, _ = create_image_with_detection()
    foreign_image_id, _ = create_image_with_detection()

    with TestingSession() as db:
        own_image = db.get(models.ShelfImage, own_image_id)
        own_shelf = db.get(models.Shelf, own_image.shelf_id)
        own_zone = db.get(models.Zone, own_shelf.zone_id)
        foreign_image = db.get(models.ShelfImage, foreign_image_id)
        foreign_shelf_id = foreign_image.shelf_id
        foreign_shelf = db.get(models.Shelf, foreign_shelf_id)
        foreign_zone = db.get(models.Zone, foreign_shelf.zone_id)
        foreign_session = models.CaptureSession(
            store_id=foreign_zone.store_id,
            shelf_id=foreign_shelf_id,
            source_type="mobile",
            capture_mode="single",
        )
        db.add(foreign_session)
        db.commit()
        foreign_session_id = foreign_session.id
        own_shelf_id = own_shelf.id
        actor = SimpleNamespace(
            id=777,
            role="SUPERVISOR",
            store_id=own_zone.store_id,
        )

    monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))

    image_bytes = BytesIO()
    Image.new("RGB", (8, 8), (20, 40, 60)).save(image_bytes, format="PNG")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(foreign_shelf_id)},
            files={"image": ("foreign.png", image_bytes.getvalue(), "image/png")},
        )
        image_bytes.seek(0)
        missing = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": "2147483000"},
            files={"image": ("missing.png", image_bytes.getvalue(), "image/png")},
        )
        foreign_session_bytes = BytesIO(image_bytes.getvalue())
        foreign_session_response = client.post(
            "/api/v1/shelf-images",
            data={
                "shelf_id": str(own_shelf_id),
                "capture_session_id": str(foreign_session_id),
            },
            files={"image": ("foreign-session.png", foreign_session_bytes.getvalue(), "image/png")},
        )
        missing_session_bytes = BytesIO(image_bytes.getvalue())
        missing_session_response = client.post(
            "/api/v1/shelf-images",
            data={
                "shelf_id": str(own_shelf_id),
                "capture_session_id": "2147483000",
            },
            files={"image": ("missing-session.png", missing_session_bytes.getvalue(), "image/png")},
        )

    assert response.status_code == missing.status_code == 404
    assert response.json() == missing.json()
    assert foreign_session_response.status_code == missing_session_response.status_code == 404
    assert foreign_session_response.json() == missing_session_response.json()
    assert not list(tmp_path.rglob("*"))
    with TestingSession() as db:
        assert db.query(models.ShelfImage).filter(
            models.ShelfImage.shelf_id == foreign_shelf_id
        ).count() == 1



def test_fusion_suppresses_inactive_visual_and_cached_ocr_candidates():
    image_id, detection_id = create_image_with_detection()
    with TestingSession() as db:
        product = models.Product(
            sku="OCR-RETIRED-01",
            name="Produto desativado",
            is_active=True,
        )
        db.add(product)
        db.flush()
        product_id = product.id
        detection = db.get(models.ShelfImageDetection, detection_id)
        detection.product_id = product_id
        detection.sku_match_status = "MATCHED"
        detection.sku_similarity = 0.97
        run = models.ShelfImageOCRRun(
            shelf_image_id=image_id,
            provider="mock-ocr",
            model_version="ocr-v1",
            status="COMPLETED",
        )
        db.add(run)
        db.flush()
        db.add(models.ShelfImageOCRMatch(
            run_id=run.id,
            detection_id=detection_id,
            suggested_product_id=product_id,
            observed_text="Produto desativado",
            ocr_confidence=0.98,
            status="SUGGESTED",
            top_score=0.99,
            margin=0.2,
            candidates=[{"product_id": product_id, "score": 0.99, "reasons": ["name"]}],
        ))
        product.is_active = False
        db.commit()

    with TestClient(app) as client:
        response = client.post(f"/api/v1/shelf-images/{image_id}/evidence-fusion")

    assert response.status_code == 200
    assert len(response.json()) == 1
    fused = response.json()[0]
    assert fused["status"] == "UNKNOWN"
    assert fused["suggested_product_id"] is None
    assert fused["visual_product_id"] is None
    assert fused["text_product_id"] is None
    assert fused["visual_status"] == "UNKNOWN"
    assert fused["text_status"] == "UNKNOWN"



def test_ocr_read_endpoints_lock_source_image_during_retention_check(monkeypatch):
    from sqlalchemy.orm import Query

    image_id, _detection_id = create_image_with_detection()
    original_with_for_update = Query.with_for_update
    locked_image_queries = []

    def record_image_lock(query, *args, **kwargs):
        descriptions = query.column_descriptions
        if descriptions and descriptions[0].get("entity") is models.ShelfImage:
            locked_image_queries.append(True)
        return original_with_for_update(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", record_image_lock)

    endpoints = [
        f"/api/v1/shelf-images/{image_id}/detections",
        f"/api/v1/shelf-images/{image_id}/ocr-runs",
        f"/api/v1/shelf-images/{image_id}/ocr-evidence",
        f"/api/v1/shelf-images/{image_id}/ocr-matches",
        f"/api/v1/shelf-images/{image_id}/evidence-fusion",
    ]
    with TestClient(app) as client:
        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 200, (endpoint, response.text)

    assert len(locked_image_queries) == len(endpoints), (
        "Every OCR/detection read must lock and refresh the source image "
        "before checking retention and returning derived evidence"
    )



def test_evidence_fusion_locks_source_image_before_loading_derived_rows(monkeypatch):
    from sqlalchemy.orm import Query

    image_id, detection_id = create_image_with_detection()
    with TestClient(app) as client:
        created = client.post(
            f"/api/v1/shelf-images/{image_id}/ocr-runs",
            json={
                "provider": "mock-ocr",
                "model_version": "mock-v1",
                "regions": [{
                    "detection_id": detection_id,
                    "text": "Produto de teste",
                    "confidence": 0.95,
                    "x_min": 0.2,
                    "y_min": 0.2,
                    "x_max": 0.6,
                    "y_max": 0.3,
                }],
            },
        )
        assert created.status_code == 201

    original_with_for_update = Query.with_for_update
    locked_image_queries = []

    def record_image_lock(query, *args, **kwargs):
        descriptions = query.column_descriptions
        if descriptions and descriptions[0].get("entity") is models.ShelfImage:
            locked_image_queries.append(True)
        return original_with_for_update(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", record_image_lock)
    with TestClient(app) as client:
        response = client.post(f"/api/v1/shelf-images/{image_id}/evidence-fusion")

    assert response.status_code == 200, response.text
    assert locked_image_queries, (
        "Evidence fusion must lock the source image before reading OCR "
        "matches or visual detections"
    )



def test_detection_review_history_locks_source_image_before_returning_reviews(monkeypatch):
    from sqlalchemy.orm import Query

    image_id, detection_id = create_image_with_detection()
    original_with_for_update = Query.with_for_update
    locked_image_queries = []

    def record_image_lock(query, *args, **kwargs):
        descriptions = query.column_descriptions
        if descriptions and descriptions[0].get("entity") is models.ShelfImage:
            locked_image_queries.append(True)
        return original_with_for_update(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", record_image_lock)
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/shelf-image-detections/{detection_id}/reviews"
        )

    assert response.status_code == 200, response.text
    assert locked_image_queries, (
        "Detection review history must lock and refresh its source image "
        "before returning derived review data"
    )




def test_reviewed_training_candidates_recheck_active_catalogue_product():
    image_id, detection_id = create_image_with_detection()
    with TestingSession() as db:
        product = models.Product(sku="TRAIN-CATALOGUE-01", name="Produto Treino", is_active=True)
        db.add(product)
        db.flush()
        product_id = product.id
        db.add(models.DetectionSkuReview(
            detection_id=detection_id,
            previous_product_id=None,
            selected_product_id=product_id,
            decision="CONFIRMED",
            reviewer_user_id=None,
            notes="approved training label",
        ))
        db.commit()

    with TestClient(app) as client:
        initial = client.get("/api/v1/training-candidates/reviewed")
        assert initial.status_code == 200, initial.text
        assert any(item["product_id"] == product_id for item in initial.json())

        with TestingSession() as db:
            db.get(models.Product, product_id).is_active = False
            db.commit()

        refreshed = client.get("/api/v1/training-candidates/reviewed")
        assert refreshed.status_code == 200, refreshed.text
        assert all(item["product_id"] != product_id for item in refreshed.json())

def test_reviewed_training_candidates_lock_images_before_catalogue_products(monkeypatch):
    from sqlalchemy.orm import Query

    image_id, detection_id = create_image_with_detection()
    with TestingSession() as db:
        product = models.Product(sku="TRAIN-LOCK-01", name="Produto Lock", is_active=True)
        db.add(product)
        db.flush()
        db.add(models.DetectionSkuReview(
            detection_id=detection_id,
            previous_product_id=None,
            selected_product_id=product.id,
            decision="CONFIRMED",
            reviewer_user_id=None,
            notes="lock-order regression",
        ))
        db.commit()

    original_with_for_update = Query.with_for_update
    lock_order = []

    def record_lock_order(query, *args, **kwargs):
        locked_entities = kwargs.get("of", ())
        if not isinstance(locked_entities, (tuple, list, set)):
            locked_entities = (locked_entities,)
        if models.ShelfImage in locked_entities:
            lock_order.append("image")
        elif query.column_descriptions and query.column_descriptions[0].get("entity") is models.Product:
            lock_order.append("product")
        return original_with_for_update(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", record_lock_order)
    with TestClient(app) as client:
        response = client.get("/api/v1/training-candidates/reviewed")

    assert response.status_code == 200, response.text
    assert "image" in lock_order, "Training candidate selection must lock source images"
    assert "product" in lock_order, "Training candidate selection must lock catalogue products"
    assert lock_order.index("image") < lock_order.index("product"), (
        "Training candidates must follow the global image -> product lock order"
    )

def test_review_queue_locks_source_images_before_returning_derived_evidence(monkeypatch):
    from sqlalchemy.orm import Query

    image_id, detection_id = create_image_with_detection()
    db = TestingSession()
    image = db.get(models.ShelfImage, image_id)
    run = models.ShelfImageOCRRun(
        shelf_image_id=image_id,
        provider="mock-ocr",
        model_version="mock-v1",
        status="COMPLETED",
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
        reason="retention lock regression",
    ))
    db.commit()
    db.close()

    original_with_for_update = Query.with_for_update
    locked_source_images = []

    def record_source_image_lock(query, *args, **kwargs):
        locked_entities = kwargs.get("of", ())
        if not isinstance(locked_entities, (tuple, list, set)):
            locked_entities = (locked_entities,)
        if models.ShelfImage in locked_entities:
            locked_source_images.append(True)
        return original_with_for_update(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", record_source_image_lock)
    with TestClient(app) as client:
        response = client.get("/api/v1/shelf-image-review-queue")

    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    assert response.json()[0]["shelf_image_id"] == image_id
    assert locked_source_images, (
        "Review queue reads must lock source images before returning derived "
        "evidence so retention transitions cannot race the response"
    )

def test_review_queue_is_scoped_to_supervisor_store_and_admin_is_global(monkeypatch):
    own_image_id, own_detection_id = create_image_with_detection()
    foreign_image_id, foreign_detection_id = create_image_with_detection()

    with TestingSession() as db:
        own_image = db.get(models.ShelfImage, own_image_id)
        foreign_image = db.get(models.ShelfImage, foreign_image_id)
        own_zone = db.get(models.Zone, db.get(models.Shelf, own_image.shelf_id).zone_id)

        supervisor = models.User(
            email="review-queue-scope-supervisor@test.local",
            full_name="Review Queue Supervisor",
            password_hash="test-hash",
            role="SUPERVISOR",
            store_id=own_zone.store_id,
            is_active=True,
        )
        admin = models.User(
            email="review-queue-scope-admin@test.local",
            full_name="Review Queue Admin",
            password_hash="test-hash",
            role="ADMIN",
            store_id=None,
            is_active=True,
        )
        employee = models.User(
            email="review-queue-scope-employee@test.local",
            full_name="Review Queue Employee",
            password_hash="test-hash",
            role="EMPLOYEE",
            store_id=own_zone.store_id,
            is_active=True,
        )
        db.add_all([supervisor, admin, employee])
        db.flush()

        for image_id, detection_id in (
            (own_image_id, own_detection_id),
            (foreign_image_id, foreign_detection_id),
        ):
            run = models.ShelfImageOCRRun(
                shelf_image_id=image_id,
                provider="scope-test",
                model_version="scope-test-v1",
                status="COMPLETED",
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
                visual_model_version="scope-test-v1",
                ocr_provider="scope-test",
                ocr_model_version="scope-test-v1",
                reason="review queue tenant isolation regression",
            ))
        db.commit()
        supervisor_id, admin_id, employee_id = supervisor.id, admin.id, employee.id

    monkeypatch.setattr(main_module, "SessionLocal", TestingSession)
    monkeypatch.setattr(main_module.settings, "app_env", "production")
    supervisor_token, _ = create_access_token(user_id=supervisor_id, role="SUPERVISOR")
    admin_token, _ = create_access_token(user_id=admin_id, role="ADMIN")
    employee_token, _ = create_access_token(user_id=employee_id, role="EMPLOYEE")

    with TestClient(app) as client:
        supervisor_response = client.get(
            "/api/v1/shelf-image-review-queue",
            headers={"Authorization": f"Bearer {supervisor_token}"},
        )
        assert supervisor_response.status_code == 200
        assert [item["shelf_image_id"] for item in supervisor_response.json()] == [own_image_id]

        admin_response = client.get(
            "/api/v1/shelf-image-review-queue",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_response.status_code == 200
        assert {item["shelf_image_id"] for item in admin_response.json()} == {
            own_image_id, foreign_image_id
        }

        employee_response = client.get(
            "/api/v1/shelf-image-review-queue",
            headers={"Authorization": f"Bearer {employee_token}"},
        )
        assert employee_response.status_code == 403

def test_jwt_middleware_and_store_scope_protect_ocr_routes(monkeypatch):
    own_image_id, own_detection_id = create_image_with_detection()
    foreign_image_id, foreign_detection_id = create_image_with_detection()

    with TestingSession() as db:
        own_image = db.get(models.ShelfImage, own_image_id)
        own_zone = db.get(
            models.Zone,
            db.get(models.Shelf, own_image.shelf_id).zone_id,
        )
        supervisor = models.User(
            email="ocr-middleware-supervisor@test.local",
            full_name="OCR Middleware Supervisor",
            password_hash="test-hash",
            role="SUPERVISOR",
            store_id=own_zone.store_id,
            is_active=True,
        )
        employee = models.User(
            email="ocr-middleware-employee@test.local",
            full_name="OCR Middleware Employee",
            password_hash="test-hash",
            role="EMPLOYEE",
            store_id=own_zone.store_id,
            is_active=True,
        )
        db.add_all([supervisor, employee])
        db.commit()
        supervisor_id, employee_id = supervisor.id, employee.id

    monkeypatch.setattr(main_module.settings, "app_env", "production")
    # The authentication middleware opens SessionLocal directly rather than
    # using FastAPI's get_db dependency override.
    monkeypatch.setattr(main_module, "SessionLocal", TestingSession)
    supervisor_token, _ = create_access_token(
        user_id=supervisor_id, role="SUPERVISOR",
    )
    employee_token, _ = create_access_token(
        user_id=employee_id, role="EMPLOYEE",
    )
    supervisor_headers = {"Authorization": f"Bearer {supervisor_token}"}
    employee_headers = {"Authorization": f"Bearer {employee_token}"}

    with TestClient(app) as client:
        own_ocr = client.post(
            f"/api/v1/shelf-images/{own_image_id}/ocr-runs",
            headers=supervisor_headers,
            json={
                "provider": "middleware-test",
                "model_version": "middleware-v1",
                "regions": [{
                    "detection_id": own_detection_id,
                    "text": "Produto da loja",
                    "confidence": 0.95,
                    "x_min": 0.1,
                    "y_min": 0.1,
                    "x_max": 0.5,
                    "y_max": 0.3,
                }],
            },
        )
        assert own_ocr.status_code == 201

        foreign_read = client.get(
            f"/api/v1/shelf-images/{foreign_image_id}/ocr-runs",
            headers=supervisor_headers,
        )
        assert foreign_read.status_code == 403

        foreign_write = client.post(
            f"/api/v1/shelf-images/{foreign_image_id}/ocr-runs",
            headers=supervisor_headers,
            json={
                "provider": "middleware-test",
                "model_version": "middleware-v1",
                "regions": [{
                    "detection_id": foreign_detection_id,
                    "text": "Tentativa noutra loja",
                    "confidence": 0.9,
                    "x_min": 0.1,
                    "y_min": 0.1,
                    "x_max": 0.5,
                    "y_max": 0.3,
                }],
            },
        )
        assert foreign_write.status_code == 403

        employee_read = client.get(
            f"/api/v1/shelf-images/{own_image_id}/ocr-runs",
            headers=employee_headers,
        )
        assert employee_read.status_code == 200

        employee_write = client.post(
            f"/api/v1/shelf-images/{own_image_id}/ocr-runs",
            headers=employee_headers,
            json={
                "provider": "middleware-test",
                "model_version": "middleware-v1",
                "regions": [],
            },
        )
        assert employee_write.status_code == 403

def test_ocr_pipeline_locks_catalogue_after_source_image_and_suppresses_inactive_visual():
    from sqlalchemy.orm import Query
    from app.product_pipeline import process_completed_ocr_run

    image_id, detection_id = create_image_with_detection()
    with TestingSession() as db:
        product = models.Product(
            sku="PIPELINE-RETIRED-01",
            name="Produto desativado durante pipeline",
            is_active=False,
        )
        db.add(product)
        db.flush()
        detection = db.get(models.ShelfImageDetection, detection_id)
        detection.product_id = product.id
        detection.sku_match_status = "MATCHED"
        detection.sku_similarity = 0.99
        run = models.ShelfImageOCRRun(
            shelf_image_id=image_id,
            provider="pipeline-test",
            model_version="pipeline-v1",
            status="COMPLETED",
        )
        db.add(run)
        db.flush()
        db.add(models.ShelfImageOCREvidence(
            run_id=run.id,
            detection_id=detection_id,
            text="Produto desativado durante pipeline",
            normalized_text="produto desativado durante pipeline",
            confidence=0.99,
            x_min=0.1,
            y_min=0.1,
            x_max=0.5,
            y_max=0.3,
            association_status="ASSIGNED",
        ))
        db.commit()

    original_with_for_update = Query.with_for_update
    lock_order = []

    def record_lock_order(query, *args, **kwargs):
        entities = query.column_descriptions
        if entities and entities[0].get("entity") is models.ShelfImage:
            lock_order.append("image")
        elif entities and entities[0].get("entity") is models.Product:
            lock_order.append("product")
        return original_with_for_update(query, *args, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(Query, "with_for_update", record_lock_order)
    try:
        with TestingSession() as db:
            db.query(models.ShelfImage).filter(
                models.ShelfImage.id == image_id
            ).with_for_update().populate_existing().one()
            counts = process_completed_ocr_run(db, image_id)
            db.commit()
            assert counts == {"ocr_matches_created": 1, "fused_evidence_created": 1}

            match = db.query(models.ShelfImageOCRMatch).one()
            assert match.suggested_product_id is None
            assert match.status == "UNKNOWN"

            fused = db.query(models.ShelfImageFusedEvidence).one()
            assert fused.status == "UNKNOWN"
            assert fused.suggested_product_id is None
            assert fused.visual_product_id is None
            assert fused.text_product_id is None
    finally:
        monkeypatch.undo()

    assert "image" in lock_order
    assert "product" in lock_order
    assert lock_order.index("image") < lock_order.index("product")



def test_image_detections_support_stable_bounded_offset_pagination():
    image_id, first_detection_id = create_image_with_detection()
    with TestingSession() as db:
        extra_detections = [
            models.ShelfImageDetection(
                shelf_image_id=image_id,
                label="product",
                confidence=0.8,
                x_min=0.1,
                y_min=0.1,
                x_max=0.4,
                y_max=0.4,
                model_version="detector-v1",
            )
            for _ in range(2)
        ]
        db.add_all(extra_detections)
        db.commit()
        expected_ids = [
            row.id
            for row in db.query(models.ShelfImageDetection)
            .filter(models.ShelfImageDetection.shelf_image_id == image_id)
            .order_by(models.ShelfImageDetection.id)
            .all()
        ]

    with TestClient(app) as client:
        first_page = client.get(
            f"/api/v1/shelf-images/{image_id}/detections?limit=1&offset=0"
        )
        second_page = client.get(
            f"/api/v1/shelf-images/{image_id}/detections?limit=1&offset=1"
        )
        clamped = client.get(
            f"/api/v1/shelf-images/{image_id}/detections?limit=0&offset=-10"
        )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert clamped.status_code == 200
    assert [item["id"] for item in first_page.json()] == [expected_ids[0]]
    assert [item["id"] for item in second_page.json()] == [expected_ids[1]]
    assert [item["id"] for item in clamped.json()] == [expected_ids[0]]
    assert first_detection_id == expected_ids[0]



def test_fused_evidence_status_pagination_applies_offset_after_catalogue_refresh():
    image_id, first_detection_id = create_image_with_detection()
    expected_consensus_ids = []

    with TestingSession() as db:
        run = models.ShelfImageOCRRun(
            shelf_image_id=image_id,
            provider="mock-ocr",
            model_version="mock-v1",
            status="COMPLETED",
        )
        db.add(run)
        db.flush()

        for index in range(6):
            if index == 0:
                detection = db.get(models.ShelfImageDetection, first_detection_id)
            else:
                detection = models.ShelfImageDetection(
                    shelf_image_id=image_id,
                    label="product",
                    confidence=0.95,
                    x_min=0.1,
                    y_min=0.1,
                    x_max=0.8,
                    y_max=0.8,
                    model_version="detector-v1",
                )
                db.add(detection)
                db.flush()

            product = models.Product(
                sku=f"FUSION-PAGE-{index}",
                name=f"Produto Fusion {index}",
                is_active=index < 3,
            )
            db.add(product)
            db.flush()
            detection.sku_match_status = "MATCHED"
            detection.product_id = product.id
            detection.sku_similarity = 0.96
            detection.sku_match_margin = 0.12

            evidence = models.ShelfImageFusedEvidence(
                ocr_run_id=run.id,
                detection_id=detection.id,
                status="CONSENSUS",
                suggested_product_id=product.id,
                visual_product_id=product.id,
                text_product_id=product.id,
                visual_status="MATCHED",
                text_status="SUGGESTED",
                visual_similarity=0.96,
                text_score=1.0,
                ocr_confidence=0.98,
                visual_model_version="visual-v1",
                ocr_provider="mock-ocr",
                ocr_model_version="mock-v1",
                reason="historical consensus",
            )
            db.add(evidence)
            db.flush()
            if product.is_active:
                expected_consensus_ids.append(evidence.id)

        db.commit()

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/shelf-images/{image_id}/evidence-fusion"
            "?status=CONSENSUS&limit=1&offset=1"
        )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [
        expected_consensus_ids[-2]
    ]


def test_fused_evidence_status_pagination_crosses_keyset_batch_boundary():
    image_id, first_detection_id = create_image_with_detection()
    expected_ids = []

    with TestingSession() as db:
        run = models.ShelfImageOCRRun(
            shelf_image_id=image_id,
            provider="batch-pagination-test",
            model_version="batch-v1",
            status="COMPLETED",
        )
        db.add(run)
        db.flush()

        for index in range(510):
            if index == 0:
                detection = db.get(models.ShelfImageDetection, first_detection_id)
            else:
                detection = models.ShelfImageDetection(
                    shelf_image_id=image_id,
                    label="product",
                    confidence=0.8,
                    x_min=0.1,
                    y_min=0.1,
                    x_max=0.5,
                    y_max=0.5,
                    model_version="batch-v1",
                )
                db.add(detection)
                db.flush()

            evidence = models.ShelfImageFusedEvidence(
                ocr_run_id=run.id,
                detection_id=detection.id,
                status="UNKNOWN",
                suggested_product_id=None,
                visual_product_id=None,
                text_product_id=None,
                visual_status="UNKNOWN",
                text_status="UNKNOWN",
                visual_model_version="batch-v1",
                ocr_provider="batch-pagination-test",
                ocr_model_version="batch-v1",
                reason="batch pagination regression",
            )
            db.add(evidence)
            db.flush()
            expected_ids.append(evidence.id)

        db.commit()

    expected_page = sorted(expected_ids, reverse=True)[500:502]
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/shelf-images/{image_id}/evidence-fusion"
            "?status=UNKNOWN&limit=2&offset=500"
        )

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()] == expected_page



def test_employee_cannot_create_or_recompute_ocr_product_evidence(monkeypatch):
    image_id, _ = create_image_with_detection()
    with TestingSession() as db:
        image = db.get(models.ShelfImage, image_id)
        shelf = db.get(models.Shelf, image.shelf_id)
        zone = db.get(models.Zone, shelf.zone_id)
        employee = models.User(
            email="ocr-evidence-employee@example.test", full_name="Operador OCR",
            password_hash="test-only-not-used", role="EMPLOYEE", store_id=zone.store_id,
            is_active=True,
        )
        db.add(employee)
        db.commit()
        db.refresh(employee)

    monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: employee)
    with TestClient(app) as client:
        created_run = client.post(
            f"/api/v1/shelf-images/{image_id}/ocr-runs",
            json={"provider": "paddleocr", "model_version": "PP-OCRv5-pt", "regions": []},
        )
        matched = client.post(f"/api/v1/shelf-images/{image_id}/ocr-matches")
        fused = client.post(f"/api/v1/shelf-images/{image_id}/evidence-fusion")
        assert [created_run.status_code, matched.status_code, fused.status_code] == [403, 403, 403]

    with TestingSession() as db:
        assert db.query(models.ShelfImageOCRRun).filter_by(shelf_image_id=image_id).count() == 0
        assert db.query(models.ShelfImageOCRMatch).count() == 0
        assert db.query(models.ShelfImageFusedEvidence).count() == 0
