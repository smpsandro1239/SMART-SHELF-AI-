from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.demo.seed import DEMO_PRODUCTS, DEMO_STORE_CODE, seed_demo_data
from app.demo.vision import MockShelfVisionProvider
from app import models


def test_mock_provider_is_deterministic_and_returns_valid_empty_facing(tmp_path):
    image = tmp_path / "shelf.png"
    image.write_bytes(b"synthetic-image-content-v1")
    provider = MockShelfVisionProvider()

    first = provider.analyze(image)
    second = provider.analyze(image)

    assert first.model_version == "mock-shelf-vision-v1"
    assert first.model_dump() == second.model_dump()
    assert len(first.detections) == 1
    detection = first.detections[0]
    assert detection.label == "empty_facing"
    assert 0.9 <= detection.confidence <= 0.99
    detection.validate_box()


def test_mock_provider_changes_geometry_when_image_digest_changes(tmp_path):
    image = tmp_path / "shelf.png"
    provider = MockShelfVisionProvider()
    image.write_bytes(b"synthetic-image-content-v1")
    first = provider.analyze(image).model_dump()
    image.write_bytes(b"synthetic-image-content-v2")
    second = provider.analyze(image).model_dump()
    assert first != second


def test_demo_seed_is_idempotent_and_generates_synthetic_asset(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            first = seed_demo_data(db, tmp_path / "assets")
            second = seed_demo_data(db, tmp_path / "assets")
            assert first["store_id"] == second["store_id"]
            assert len(first["shelf_ids"]) == 3
            assert len(first["product_ids"]) == len(DEMO_PRODUCTS) == 15
            assert Path(second["image_path"]).is_file()
            assert db.query(models.Store).filter_by(code=DEMO_STORE_CODE).count() == 1
            assert db.query(models.User).filter(models.User.email.like("%@demo.smart-shelf.local")).count() == 3
            assert db.query(models.Product).filter(models.Product.sku.like("DEMO-%")).count() == 15
            assert db.query(models.InventorySnapshot).filter_by(store_id=first["store_id"], source="MANUAL").count() == 15
            assert db.query(models.InventoryFreshnessPolicy).filter_by(store_id=first["store_id"], source="MANUAL").count() == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
