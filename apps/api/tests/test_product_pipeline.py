import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models
from app.product_pipeline import process_completed_ocr_run


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = models.Store(code="PIPELINE", name="Pipeline test")
        session.add(store)
        session.flush()
        zone = models.Zone(store_id=store.id, name="Zona")
        session.add(zone)
        session.flush()
        shelf = models.Shelf(zone_id=zone.id, code="P-01")
        session.add(shelf)
        session.flush()
        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="pipeline.jpg",
            storage_path="/tmp/pipeline.jpg",
            mime_type="image/jpeg",
            file_size_bytes=100,
            sha256="a" * 64,
            analysis_status="COMPLETED",
            model_version="detector-v1",
        )
        product_a = models.Product(
            sku="LEITE-1L",
            name="Leite Meio-Gordo 1 L",
            brand="Marca A",
            unit="1 L",
            is_active=True,
        )
        product_b = models.Product(
            sku="BEBIDA-1L",
            name="Bebida de Aveia 1 L",
            brand="Marca B",
            unit="1 L",
            is_active=True,
        )
        session.add_all([image, product_a, product_b])
        session.flush()
        session.add_all([
            models.ShelfProduct(shelf_id=shelf.id, product_id=product_a.id),
            models.ShelfProduct(shelf_id=shelf.id, product_id=product_b.id),
        ])
        session.flush()
        detection_a = models.ShelfImageDetection(
            shelf_image_id=image.id,
            product_id=product_a.id,
            label="product",
            confidence=0.95,
            x_min=0.05,
            y_min=0.1,
            x_max=0.45,
            y_max=0.9,
            model_version="detector-v1",
            embedding_model_version="embed-v1",
            sku_match_status="MATCHED",
            sku_similarity=0.97,
            sku_match_margin=0.12,
        )
        detection_b = models.ShelfImageDetection(
            shelf_image_id=image.id,
            product_id=product_a.id,
            label="product",
            confidence=0.91,
            x_min=0.5,
            y_min=0.1,
            x_max=0.95,
            y_max=0.9,
            model_version="detector-v1",
            embedding_model_version="embed-v1",
            sku_match_status="MATCHED",
            sku_similarity=0.94,
            sku_match_margin=0.1,
        )
        session.add_all([detection_a, detection_b])
        session.flush()
        run = models.ShelfImageOCRRun(
            shelf_image_id=image.id,
            provider="fake-ocr",
            model_version="test-v1",
            status="COMPLETED",
        )
        session.add(run)
        session.flush()
        session.add_all([
            models.ShelfImageOCREvidence(
                run_id=run.id,
                detection_id=detection_a.id,
                text="Leite Meio-Gordo 1 L",
                normalized_text="leite meio gordo 1 l",
                confidence=0.96,
                x_min=0.1,
                y_min=0.2,
                x_max=0.4,
                y_max=0.7,
                association_status="ASSIGNED",
            ),
            models.ShelfImageOCREvidence(
                run_id=run.id,
                detection_id=detection_b.id,
                text="Bebida de Aveia 1 L",
                normalized_text="bebida de aveia 1 l",
                confidence=0.95,
                x_min=0.55,
                y_min=0.2,
                x_max=0.9,
                y_max=0.7,
                association_status="ASSIGNED",
            ),
        ])
        session.flush()
        session.info["image_id"] = image.id
        session.info["product_a_id"] = product_a.id
        session.info["product_b_id"] = product_b.id
        session.info["detection_a_id"] = detection_a.id
        session.info["detection_b_id"] = detection_b.id
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_pipeline_matches_and_fuses_ocr_with_visual_evidence(db):
    result = process_completed_ocr_run(db, db.info["image_id"])

    assert result == {"ocr_matches_created": 2, "fused_evidence_created": 2}
    matches = {
        row.detection_id: row
        for row in db.query(models.ShelfImageOCRMatch).all()
    }
    fused = {
        row.detection_id: row
        for row in db.query(models.ShelfImageFusedEvidence).all()
    }

    match_a = matches[db.info["detection_a_id"]]
    match_b = matches[db.info["detection_b_id"]]
    assert match_a.status == "SUGGESTED"
    assert match_a.suggested_product_id == db.info["product_a_id"]
    assert match_b.status == "SUGGESTED"
    assert match_b.suggested_product_id == db.info["product_b_id"]

    assert fused[db.info["detection_a_id"]].status == "CONSENSUS"
    assert fused[db.info["detection_a_id"]].suggested_product_id == db.info["product_a_id"]
    assert fused[db.info["detection_b_id"]].status == "CONFLICT"
    assert fused[db.info["detection_b_id"]].suggested_product_id is None
    assert db.query(models.InventorySnapshot).count() == 0


def test_pipeline_is_idempotent_and_preserves_existing_evidence(db):
    first = process_completed_ocr_run(db, db.info["image_id"])
    second = process_completed_ocr_run(db, db.info["image_id"])

    assert first == {"ocr_matches_created": 2, "fused_evidence_created": 2}
    assert second == {"ocr_matches_created": 0, "fused_evidence_created": 0}
    assert db.query(models.ShelfImageOCRMatch).count() == 2
    assert db.query(models.ShelfImageFusedEvidence).count() == 2


def test_pipeline_abstains_for_low_confidence_ocr(db):
    region = db.query(models.ShelfImageOCREvidence).filter_by(
        detection_id=db.info["detection_a_id"]
    ).one()
    region.confidence = 0.4
    db.flush()

    process_completed_ocr_run(db, db.info["image_id"])

    match = db.query(models.ShelfImageOCRMatch).filter_by(
        detection_id=db.info["detection_a_id"]
    ).one()
    fused = db.query(models.ShelfImageFusedEvidence).filter_by(
        detection_id=db.info["detection_a_id"]
    ).one()
    assert match.status == "UNKNOWN"
    assert match.suggested_product_id is None
    assert fused.status == "VISUAL_ONLY"


def test_worker_automatically_runs_catalogue_matching_and_fusion(db, tmp_path, monkeypatch):
    import app.vision_worker as worker
    from app.ocr_paddle import OCRRegion
    from app.product_text import OCRText
    from app.vision import DetectionResult, VisionAnalysis
    from app.vision_worker import process_next_image

    store = models.Store(code="AUTO-PIPELINE", name="Automatic pipeline")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="AUTO-01")
    db.add(shelf)
    db.flush()
    storage_root = tmp_path / "storage"
    monkeypatch.setattr(worker.settings, "image_storage_path", str(storage_root))
    image_path = storage_root / str(store.id) / "automatic.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"test-image")
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="automatic.jpg",
        storage_path=str(image_path),
        mime_type="image/jpeg",
        file_size_bytes=image_path.stat().st_size,
        sha256="b" * 64,
        analysis_status="PENDING",
    )
    db.add(image)
    db.flush()
    image_id = image.id

    class FakeVision:
        def analyze(self, path):
            return VisionAnalysis(
                model_version="detector-test-v1",
                detections=[
                    DetectionResult(
                        label="product",
                        confidence=0.95,
                        x_min=0.1,
                        y_min=0.1,
                        x_max=0.8,
                        y_max=0.8,
                    )
                ],
            )

    class FakeOCR:
        def recognize(self, path):
            return (
                OCRRegion(
                    OCRText("Leite Meio-Gordo 1 L", 0.94),
                    0.2,
                    0.2,
                    0.6,
                    0.5,
                ),
            )

    processed_id = process_next_image(db, FakeVision(), ocr_provider=FakeOCR())

    assert processed_id == image_id
    processed_image = db.get(models.ShelfImage, image_id)
    assert processed_image.analysis_status == "COMPLETED"

    run = db.query(models.ShelfImageOCRRun).filter_by(
        shelf_image_id=image_id,
        status="COMPLETED",
    ).one()
    match = db.query(models.ShelfImageOCRMatch).filter_by(run_id=run.id).one()
    fused = db.query(models.ShelfImageFusedEvidence).filter_by(ocr_run_id=run.id).one()

    assert match.status == "SUGGESTED"
    assert match.suggested_product_id == db.info["product_a_id"]
    assert fused.status == "TEXT_ONLY"
    assert fused.suggested_product_id == db.info["product_a_id"]
    assert db.query(models.InventorySnapshot).count() == 0


def test_worker_requeues_only_abandoned_active_processing_jobs(db, monkeypatch):
    from datetime import timedelta

    from app import vision_worker

    now = models.utc_now()
    stale = models.ShelfImage(
        shelf_id=db.query(models.Shelf).first().id,
        original_filename="stale.jpg",
        storage_path="/tmp/stale.jpg",
        mime_type="image/jpeg",
        file_size_bytes=100,
        sha256="b" * 64,
        analysis_status="PROCESSING",
        analysis_started_at=now - timedelta(hours=25),
        retention_status="ACTIVE",
    )
    recent = models.ShelfImage(
        shelf_id=db.query(models.Shelf).first().id,
        original_filename="recent.jpg",
        storage_path="/tmp/recent.jpg",
        mime_type="image/jpeg",
        file_size_bytes=100,
        sha256="c" * 64,
        analysis_status="PROCESSING",
        analysis_started_at=now - timedelta(minutes=5),
        retention_status="ACTIVE",
    )
    restricted = models.ShelfImage(
        shelf_id=db.query(models.Shelf).first().id,
        original_filename="restricted.jpg",
        storage_path="/tmp/restricted.jpg",
        mime_type="image/jpeg",
        file_size_bytes=100,
        sha256="e" * 64,
        analysis_status="PROCESSING",
        analysis_started_at=now - timedelta(hours=25),
        retention_status="RESTRICTED",
    )
    db.add_all([stale, recent, restricted])
    db.flush()
    stale_id, recent_id, restricted_id = stale.id, recent.id, restricted.id

    recovered = vision_worker.requeue_stale_processing_images(
        db,
        stale_after_seconds=86400,
    )

    assert recovered == 1
    assert db.get(models.ShelfImage, stale_id).analysis_status == "PENDING"
    assert db.get(models.ShelfImage, stale_id).analysis_started_at is None
    assert "Recovered abandoned" in db.get(models.ShelfImage, stale_id).analysis_error
    assert db.get(models.ShelfImage, recent_id).analysis_status == "PROCESSING"
    assert db.get(models.ShelfImage, restricted_id).analysis_status == "PROCESSING"


def test_worker_discards_result_when_processing_lease_changes_during_inference(
    db, tmp_path, monkeypatch
):
    from datetime import timedelta

    import app.vision_worker as worker
    from app.vision import DetectionResult, VisionAnalysis

    store = models.Store(code="LEASE-TEST", name="Lease test")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="LEASE-01")
    db.add(shelf)
    db.flush()

    storage_root = tmp_path / "storage"
    monkeypatch.setattr(worker.settings, "image_storage_path", str(storage_root))
    image_path = storage_root / str(store.id) / "lease.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"lease-test-image")
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="lease.jpg",
        storage_path=str(image_path),
        mime_type="image/jpeg",
        file_size_bytes=image_path.stat().st_size,
        sha256="d" * 64,
        analysis_status="PENDING",
    )
    db.add(image)
    db.flush()
    image_id = image.id

    class LeaseChangingVision:
        def analyze(self, path):
            claimed = db.get(models.ShelfImage, image_id)
            claimed.analysis_started_at = models.utc_now() + timedelta(seconds=1)
            db.commit()
            return VisionAnalysis(
                model_version="detector-lease-test",
                detections=[
                    DetectionResult(
                        label="product",
                        confidence=0.95,
                        x_min=0.1,
                        y_min=0.1,
                        x_max=0.8,
                        y_max=0.8,
                    )
                ],
            )

    processed_id = worker.process_next_image(db, LeaseChangingVision())

    assert processed_id == image_id
    persisted_image = db.get(models.ShelfImage, image_id)
    assert persisted_image.analysis_status == "PROCESSING"
    assert persisted_image.analysis_started_at is not None
    assert db.query(models.ShelfImageDetection).filter_by(
        shelf_image_id=image_id
    ).count() == 0


def test_worker_records_ocr_failure_without_losing_visual_detections(db, monkeypatch):
    import app.vision_worker as worker

    image_id = db.info["image_id"]
    detections = (
        db.query(models.ShelfImageDetection)
        .filter_by(shelf_image_id=image_id)
        .order_by(models.ShelfImageDetection.id.asc())
        .all()
    )
    detection_ids = [row.id for row in detections]

    class BrokenOCR:
        def recognize(self, path):
            raise RuntimeError("simulated OCR provider outage")

    worker.persist_ocr_evidence(
        db,
        image_id,
        __import__("pathlib").Path("/tmp/not-read-by-provider.jpg"),
        detections,
        BrokenOCR(),
    )

    failed_run = db.query(models.ShelfImageOCRRun).filter_by(
        shelf_image_id=image_id,
        status="FAILED",
    ).one()
    assert failed_run.provider == worker.settings.ocr_provider_name
    assert failed_run.model_version == worker.settings.ocr_model_version
    assert db.query(models.ShelfImageOCREvidence).filter_by(
        run_id=failed_run.id
    ).count() == 0
    assert [
        row.id
        for row in db.query(models.ShelfImageDetection)
        .filter_by(shelf_image_id=image_id)
        .order_by(models.ShelfImageDetection.id.asc())
        .all()
    ] == detection_ids
