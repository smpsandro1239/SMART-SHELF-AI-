import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models
from app.vision import DetectionResult
from app.vision_worker import resolve_sku_match


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        reviewer = models.User(
            email="reviewer@worker.test",
            full_name="Reviewer",
            password_hash="test-hash",
            role="ADMIN",
            is_active=True,
        )
        product = models.Product(sku="SKU-WORKER-1", name="Produto teste")
        session.add_all([reviewer, product])
        session.flush()
        session.info["reviewer_id"] = reviewer.id
        session.info["product_id"] = product.id
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def add_approved_exemplar(db, product_id, reviewer_id, vector, digest):
    db.add(models.ProductEmbeddingExemplar(
        product_id=product_id,
        embedding=vector,
        embedding_dimension=len(vector),
        model_version="embed-v1",
        image_sha256=digest * 64,
        licence="store-owned-test-image",
        review_status="APPROVED",
        reviewed_by_user_id=reviewer_id,
        reviewed_at=models.utc_now(),
    ))
    db.flush()


def test_worker_abstains_when_provider_does_not_return_embedding(db):
    detection = DetectionResult(
        label="product", confidence=0.9,
        x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
    )
    result = resolve_sku_match(db, detection)
    assert result == {"product_id": None, "status": "UNKNOWN", "similarity": None, "margin": None}


def test_worker_matches_only_approved_exemplar_of_same_embedding_version(db):
    add_approved_exemplar(
        db, db.info["product_id"], db.info["reviewer_id"], [1.0, 0.0, 0.0], "a"
    )
    detection = DetectionResult(
        label="product", confidence=0.9,
        x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
        embedding=[0.99, 0.01, 0.0],
        embedding_model_version="embed-v1",
    )
    result = resolve_sku_match(db, detection)
    assert result["status"] == "MATCHED"
    assert result["product_id"] == db.info["product_id"]
    assert result["similarity"] > 0.99


def test_worker_abstains_for_unapproved_or_different_version_exemplars(db):
    product_id = db.info["product_id"]
    db.add(models.ProductEmbeddingExemplar(
        product_id=product_id,
        embedding=[1.0, 0.0, 0.0],
        embedding_dimension=3,
        model_version="embed-v2",
        image_sha256="b" * 64,
        licence="store-owned-test-image",
        review_status="PENDING",
    ))
    db.flush()
    detection = DetectionResult(
        label="product", confidence=0.9,
        x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
        embedding=[1.0, 0.0, 0.0],
        embedding_model_version="embed-v1",
    )
    result = resolve_sku_match(db, detection)
    assert result["status"] == "UNKNOWN"
    assert result["product_id"] is None


def test_detection_rejects_embedding_without_model_version():
    with pytest.raises(ValueError):
        DetectionResult(
            label="product", confidence=0.9,
            x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
            embedding=[1.0, 0.0],
        )


def test_worker_reuses_registry_for_detections_with_same_embedding_version(db, monkeypatch):
    import app.vision_worker as worker

    product_id = db.info["product_id"]
    add_approved_exemplar(
        db, product_id, db.info["reviewer_id"], [1.0, 0.0, 0.0], "c"
    )
    calls = []
    original = worker.build_approved_product_registry

    def counted_registry(session, *, model_version, **kwargs):
        calls.append(model_version)
        return original(session, model_version=model_version, **kwargs)

    monkeypatch.setattr(worker, "build_approved_product_registry", counted_registry)
    cache = {}
    detections = [
        DetectionResult(
            label="product", confidence=0.9,
            x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
            embedding=[1.0, 0.0, 0.0],
            embedding_model_version="embed-v1",
        )
        for _ in range(3)
    ]

    results = [worker.resolve_sku_match(db, item, cache) for item in detections]

    assert all(item["status"] == "MATCHED" for item in results)
    assert calls == ["embed-v1"]



def test_worker_uses_configured_similarity_threshold(db, monkeypatch):
    import app.vision_worker as worker

    add_approved_exemplar(
        db, db.info["product_id"], db.info["reviewer_id"], [1.0, 0.0, 0.0], "d"
    )
    monkeypatch.setattr(worker.settings, "product_matching_min_similarity", 1.0)
    detection = DetectionResult(
        label="product", confidence=0.9,
        x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
        embedding=[0.99, 0.01, 0.0],
        embedding_model_version="embed-v1",
    )

    result = worker.resolve_sku_match(db, detection)

    assert result["status"] == "UNKNOWN"
    assert result["product_id"] is None


def test_worker_ocr_persists_assigned_and_unassigned_regions_without_stock_mutation(db, tmp_path, monkeypatch):
    from app.ocr_paddle import OCRRegion
    from app.product_text import OCRText
    from app.vision_worker import persist_ocr_evidence

    store = models.Store(code="OCR-WORKER", name="OCR Worker")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="OCR-01")
    db.add(shelf)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id, original_filename="worker.jpg",
        storage_path=str(tmp_path / "worker.jpg"), mime_type="image/jpeg",
        file_size_bytes=10, sha256="e" * 64, analysis_status="PROCESSING",
        model_version="detector-v1",
    )
    db.add(image)
    db.flush()
    detection = models.ShelfImageDetection(
        shelf_image_id=image.id, label="product", confidence=0.9,
        x_min=0.1, y_min=0.1, x_max=0.6, y_max=0.8,
        model_version="detector-v1",
    )
    db.add(detection)
    db.flush()

    class FakeOCR:
        def recognize(self, path):
            return (
                OCRRegion(OCRText("Leite Meio-Gordo 1 L", 0.94), 0.2, 0.2, 0.5, 0.3),
                OCRRegion(OCRText("PROMOÇÃO", 0.8), 0.8, 0.05, 0.95, 0.1),
            )

    persist_ocr_evidence(db, image.id, tmp_path / "worker.jpg", [detection], FakeOCR())
    db.flush()
    run = db.query(models.ShelfImageOCRRun).filter_by(shelf_image_id=image.id).one()
    evidence = db.query(models.ShelfImageOCREvidence).filter_by(run_id=run.id).order_by(models.ShelfImageOCREvidence.id).all()
    assert run.status == "COMPLETED"
    assert evidence[0].detection_id == detection.id
    assert evidence[0].association_status == "ASSIGNED"
    assert evidence[1].detection_id is None
    assert evidence[1].association_status == "UNASSIGNED"
    assert db.query(models.InventorySnapshot).count() == 0


def test_optional_ocr_failure_is_recorded_without_raising_or_mutating_inventory(db, tmp_path):
    from app.vision_worker import persist_ocr_evidence

    store = models.Store(code="OCR-FAIL", name="OCR Failure")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="OCR-FAIL-01")
    db.add(shelf)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id, original_filename="failed.jpg",
        storage_path=str(tmp_path / "failed.jpg"), mime_type="image/jpeg",
        file_size_bytes=10, sha256="f" * 64, analysis_status="COMPLETED",
        model_version="detector-v1",
    )
    db.add(image)
    db.flush()

    class BrokenOCR:
        def recognize(self, path):
            raise RuntimeError("simulated OCR runtime failure")

    persist_ocr_evidence(db, image.id, tmp_path / "failed.jpg", [], BrokenOCR())
    db.flush()
    run = db.query(models.ShelfImageOCRRun).filter_by(shelf_image_id=image.id).one()
    assert run.status == "FAILED"
    assert db.query(models.InventorySnapshot).count() == 0



def test_worker_does_not_claim_restricted_pending_images(db, tmp_path):
    import app.vision_worker as worker

    store = models.Store(code="RESTRICTED-WORKER", name="Restricted Worker")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="RESTRICTED-01")
    db.add(shelf)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="restricted.jpg",
        storage_path=str(tmp_path / "restricted.jpg"),
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256="9" * 64,
        analysis_status="PENDING",
        retention_status="RESTRICTED",
    )
    db.add(image)
    db.flush()

    class MustNotRun:
        def analyze(self, path):
            raise AssertionError("restricted image must not be sent to inference")

    assert worker.process_next_image(db, MustNotRun()) is None
    db.refresh(image)
    assert image.analysis_status == "PENDING"
