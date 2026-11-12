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
