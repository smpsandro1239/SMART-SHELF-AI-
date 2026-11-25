from pathlib import Path

import pytest
from PIL import Image
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
            first_snapshot = db.query(models.InventorySnapshot).filter_by(
                store_id=first["store_id"], product_id=first["product_ids"][0], source="MANUAL"
            ).one()
            assert float(first_snapshot.on_hand_quantity) == 4
            assert db.query(models.InventoryFreshnessPolicy).filter_by(store_id=first["store_id"], source="MANUAL").count() == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_synthetic_asset_repairs_corruption_and_is_deterministic(tmp_path):
    from app.demo.seed import create_synthetic_shelf_image

    destination = tmp_path / "assets" / "synthetic-shelf.png"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"not-a-png")

    create_synthetic_shelf_image(destination)
    with Image.open(destination) as generated:
        assert generated.format == "PNG"
        assert generated.size == (1200, 700)
        generated.verify()

    first_bytes = destination.read_bytes()
    create_synthetic_shelf_image(destination)
    assert destination.read_bytes() == first_bytes


def test_synthetic_asset_refuses_symlink_destination(tmp_path):
    from app.demo.seed import create_synthetic_shelf_image

    target = tmp_path / "keep.txt"
    target.write_text("must remain unchanged", encoding="utf-8")
    destination = tmp_path / "assets" / "synthetic-shelf.png"
    destination.parent.mkdir(parents=True)
    try:
        destination.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("Symlinks are not available in this environment")

    with pytest.raises(ValueError, match="symlink"):
        create_synthetic_shelf_image(destination)
    assert target.read_text(encoding="utf-8") == "must remain unchanged"


def test_mock_provider_persists_detections_through_existing_worker(tmp_path, monkeypatch):
    from app.config import settings
    from app.vision_worker import process_next_image

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            store = models.Store(code="DEMO-WORKER", name="Demo worker store")
            db.add(store)
            db.flush()
            zone = models.Zone(store_id=store.id, name="Demo zone")
            db.add(zone)
            db.flush()
            shelf = models.Shelf(zone_id=zone.id, code="DEMO-WORKER-01")
            db.add(shelf)
            db.flush()
            store_root = tmp_path / str(store.id)
            store_root.mkdir(parents=True)
            image_path = store_root / "synthetic.png"
            image_path.write_bytes(b"synthetic-shelf-worker-payload")
            image = models.ShelfImage(
                shelf_id=shelf.id,
                original_filename="synthetic.png",
                storage_path=str(image_path),
                mime_type="image/png",
                file_size_bytes=image_path.stat().st_size,
                sha256="b" * 64,
                analysis_status="PENDING",
                retention_status="ACTIVE",
            )
            db.add(image)
            db.commit()
            image_id = image.id

            monkeypatch.setattr(settings, "image_storage_path", str(tmp_path))
            processed = process_next_image(db, MockShelfVisionProvider())

            assert processed == image_id
            persisted = db.get(models.ShelfImage, image_id)
            detections = db.query(models.ShelfImageDetection).filter_by(shelf_image_id=image_id).all()
            assert persisted.analysis_status == "COMPLETED"
            assert persisted.model_version == "mock-shelf-vision-v1"
            assert len(detections) == 1
            assert detections[0].label == "empty_facing"
            assert detections[0].sku_match_status == "UNKNOWN"
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
