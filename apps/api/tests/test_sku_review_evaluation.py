from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.sku_review_evaluation import (
    aggregate_reviewed_predictions,
    build_reviewed_prediction_report,
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        store = models.Store(code="EVAL-01", name="Evaluation store")
        session.add(store)
        session.flush()
        zone = models.Zone(store_id=store.id, name="Zone")
        session.add(zone)
        session.flush()
        shelf = models.Shelf(zone_id=zone.id, code="E-01")
        session.add(shelf)
        session.flush()
        product_a = models.Product(sku="EVAL-A", name="Product A", is_active=True)
        product_b = models.Product(sku="EVAL-B", name="Product B", is_active=True)
        session.add_all([product_a, product_b])
        session.flush()
        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="evaluation.jpg",
            storage_path="/tmp/evaluation.jpg",
            mime_type="image/jpeg",
            file_size_bytes=100,
            sha256="c" * 64,
            analysis_status="COMPLETED",
            model_version="detector-v1",
        )
        session.add(image)
        session.flush()

        base_time = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
        detections = []
        for index in range(3):
            detection = models.ShelfImageDetection(
                shelf_image_id=image.id,
                product_id=product_a.id,
                label="product",
                confidence=0.95,
                x_min=0.1 + index * 0.1,
                y_min=0.1,
                x_max=0.4 + index * 0.1,
                y_max=0.8,
                model_version="detector-v1",
                embedding_model_version="embed-v1",
                sku_match_status="MATCHED",
            )
            session.add(detection)
            detections.append(detection)
        session.flush()

        reviews = [
            models.DetectionSkuReview(
                detection_id=detections[0].id,
                previous_product_id=product_a.id,
                selected_product_id=product_b.id,
                decision="CORRECTED",
                created_at=base_time,
            ),
            models.DetectionSkuReview(
                detection_id=detections[1].id,
                previous_product_id=product_a.id,
                selected_product_id=None,
                decision="REJECTED",
                created_at=base_time,
            ),
            models.DetectionSkuReview(
                detection_id=detections[2].id,
                previous_product_id=product_a.id,
                selected_product_id=product_a.id,
                decision="CONFIRMED",
                created_at=base_time,
            ),
        ]
        session.add_all(reviews)
        session.flush()

        def add_fusion(detection, predicted_id, status, created_at, version="embed-v1"):
            run = models.ShelfImageOCRRun(
                shelf_image_id=image.id,
                provider="test-ocr",
                model_version="ocr-test-v1",
                status="COMPLETED",
                created_at=created_at,
            )
            session.add(run)
            session.flush()
            session.add(models.ShelfImageFusedEvidence(
                ocr_run_id=run.id,
                detection_id=detection.id,
                status=status,
                suggested_product_id=predicted_id,
                visual_product_id=predicted_id,
                text_product_id=None,
                visual_status="MATCHED" if predicted_id else "UNKNOWN",
                text_status="UNKNOWN",
                visual_similarity=0.9 if predicted_id else None,
                text_score=None,
                ocr_confidence=0.9,
                visual_model_version=version,
                ocr_provider="test-ocr",
                ocr_model_version="ocr-test-v1",
                reason="test evidence",
                created_at=created_at,
            ))

        add_fusion(detections[0], product_a.id, "CONSENSUS", base_time - timedelta(minutes=1))
        # This later prediction must not leak into the historical evaluation.
        add_fusion(detections[0], product_b.id, "CONSENSUS", base_time + timedelta(minutes=1))
        add_fusion(detections[1], product_a.id, "VISUAL_ONLY", base_time - timedelta(minutes=1))
        add_fusion(detections[2], None, "UNKNOWN", base_time - timedelta(minutes=1))
        session.flush()
        yield session, store.id, product_a.id, product_b.id
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_aggregate_reports_precision_coverage_and_false_accepts():
    report = aggregate_reviewed_predictions([
        {
            "expected_product_id": 2,
            "predicted_product_id": 1,
            "fusion_status": "CONFLICT",
            "review_decision": "CORRECTED",
            "model_version": "embed-v1",
        },
        {
            "expected_product_id": None,
            "predicted_product_id": 1,
            "fusion_status": "VISUAL_ONLY",
            "review_decision": "REJECTED",
            "model_version": "embed-v1",
        },
        {
            "expected_product_id": 1,
            "predicted_product_id": None,
            "fusion_status": "UNKNOWN",
            "review_decision": "CONFIRMED",
            "model_version": "embed-v1",
        },
    ])

    assert report["sample_count"] == 3
    assert report["incorrect_known_matches"] == 1
    assert report["false_accepts_on_rejected_detections"] == 1
    assert report["missed_known_products"] == 1
    assert report["precision_when_sku_predicted"] == 0.0
    assert report["known_product_coverage"] == 0.5
    assert report["unknown_false_accept_rate"] == 1.0
    assert report["by_model_version"]["embed-v1"]["sample_count"] == 3


def test_database_report_uses_prediction_available_at_review_time(db):
    session, store_id, product_a_id, product_b_id = db

    report = build_reviewed_prediction_report(session, store_id=store_id)

    assert report["sample_count"] == 3
    assert report["latest_review_count"] == 3
    assert report["correct_matches"] == 0
    assert report["incorrect_known_matches"] == 1
    assert report["false_accepts_on_rejected_detections"] == 1
    assert report["missed_known_products"] == 1
    assert report["reviewed_detections_without_matching_fusion"] == 0
    assert report["by_model_version"]["embed-v1"]["sample_count"] == 3


def test_database_report_can_filter_by_embedding_model_version(db):
    session, store_id, _, _ = db

    report = build_reviewed_prediction_report(
        session,
        store_id=store_id,
        model_version="other-model",
    )

    assert report["sample_count"] == 0
    assert report["model_version_filter"] == "other-model"
