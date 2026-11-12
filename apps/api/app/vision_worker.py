"""One-shot worker for pending shelf-image inference jobs.

A real provider is supplied through VISION_PROVIDER_FACTORY=module:factory.
No provider is enabled by default; pending images remain untouched.
"""
import argparse
import importlib
import logging
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app import models
from app.vision import VisionAnalysis, VisionProviderNotConfigured

logger = logging.getLogger("smart_shelf.vision_worker")


def load_provider():
    factory_path = settings.vision_provider_factory.strip()
    if not factory_path:
        raise VisionProviderNotConfigured(
            "VISION_PROVIDER_FACTORY is empty; configure a real inference provider before processing images."
        )
    module_name, separator, attribute = factory_path.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("VISION_PROVIDER_FACTORY must use the format 'python.module:factory'")
    factory = getattr(importlib.import_module(module_name), attribute)
    provider = factory()
    if not callable(getattr(provider, "analyze", None)):
        raise TypeError("Vision provider must implement analyze(image_path)")
    return provider


def process_next_image(db: Session, provider) -> int | None:
    image = (
        db.query(models.ShelfImage)
        .filter(models.ShelfImage.analysis_status == "PENDING")
        .order_by(models.ShelfImage.created_at.asc(), models.ShelfImage.id.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if image is None:
        return None

    image_id = image.id
    image_path = Path(image.storage_path)
    image.analysis_status = "PROCESSING"
    image.analysis_error = None
    image.analysis_started_at = models.utc_now()
    image.analysis_completed_at = None
    db.commit()

    try:
        if not image_path.is_file():
            raise FileNotFoundError("Stored shelf image is unavailable")
        result = VisionAnalysis.model_validate(provider.analyze(image_path))
        for detection in result.detections:
            detection.validate_box()
        db.query(models.ShelfImageDetection).filter_by(shelf_image_id=image_id).delete()
        for detection in result.detections:
            db.add(models.ShelfImageDetection(
                shelf_image_id=image_id,
                product_id=detection.product_id,
                label=detection.label,
                confidence=detection.confidence,
                x_min=detection.x_min,
                y_min=detection.y_min,
                x_max=detection.x_max,
                y_max=detection.y_max,
                model_version=result.model_version,
            ))
        image = db.get(models.ShelfImage, image_id)
        image.analysis_status = "COMPLETED"
        image.analysis_error = None
        image.model_version = result.model_version
        image.analysis_completed_at = models.utc_now()
        db.commit()
    except Exception as exc:
        db.rollback()
        image = db.get(models.ShelfImage, image_id)
        if image is not None:
            image.analysis_status = "FAILED"
            image.analysis_error = f"{type(exc).__name__}: processing failed"
            image.analysis_completed_at = models.utc_now()
            db.commit()
        logger.exception("Image analysis failed for shelf image %s", image_id)
    return image_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Process pending SMART SHELF AI image-analysis jobs")
    parser.add_argument("--once", action="store_true", help="Process at most one pending image and exit")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between queue checks")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        provider = load_provider()
    except VisionProviderNotConfigured as exc:
        logger.error("%s", exc)
        return 2

    while True:
        db = SessionLocal()
        try:
            image_id = process_next_image(db, provider)
        finally:
            db.close()
        if image_id is None and args.once:
            return 0
        if args.once:
            return 0
        if image_id is None:
            time.sleep(max(0.5, args.poll_interval))


if __name__ == "__main__":
    raise SystemExit(main())
