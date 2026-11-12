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
