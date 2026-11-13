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
from app.product_embedding_service import build_approved_product_registry
from app.product_ocr_association import associate_ocr_regions
from app.product_text import normalize_product_text
from app.product_pipeline import process_completed_ocr_run

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



def load_ocr_provider():
    """Load an optional OCR provider; vision processing remains independent."""
    factory_path = settings.ocr_provider_factory.strip()
    if not factory_path:
        return None
    module_name, separator, attribute = factory_path.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("OCR_PROVIDER_FACTORY must use the format 'python.module:factory'")
    factory = getattr(importlib.import_module(module_name), attribute)
    provider = factory()
    if not callable(getattr(provider, "recognize", None)):
        raise TypeError("OCR provider must implement recognize(image_path)")
    return provider


def persist_ocr_evidence(db: Session, image_id: int, image_path: Path, detections, provider) -> None:
    """Persist OCR regions in an isolated savepoint; OCR failures never discard vision."""
    try:
        with db.begin_nested():
            run = models.ShelfImageOCRRun(
                shelf_image_id=image_id,
                provider=settings.ocr_provider_name,
                model_version=settings.ocr_model_version,
                status="COMPLETED",
            )
            db.add(run)
            db.flush()
            regions = tuple(provider.recognize(image_path))
            associations = associate_ocr_regions(detections, regions)
            assigned_detection_by_region = {}
            for association in associations:
                detection_id = detections[association.detection_index].id
                for region in association.regions:
                    assigned_detection_by_region[id(region)] = detection_id
            for region in regions:
                normalized = normalize_product_text(region.text.text)
                if not normalized:
                    continue
                detection_id = assigned_detection_by_region.get(id(region))
                db.add(models.ShelfImageOCREvidence(
                    run_id=run.id,
                    detection_id=detection_id,
                    text=region.text.text.strip(),
                    normalized_text=normalized[:1000],
                    confidence=region.text.confidence,
                    x_min=region.x_min,
                    y_min=region.y_min,
                    x_max=region.x_max,
                    y_max=region.y_max,
                    association_status="ASSIGNED" if detection_id is not None else "UNASSIGNED",
                ))
            db.flush()
    except Exception:
        logger.exception("Optional OCR processing failed for shelf image %s; visual results are retained", image_id)
        db.add(models.ShelfImageOCRRun(
            shelf_image_id=image_id,
            provider=settings.ocr_provider_name,
            model_version=settings.ocr_model_version,
            status="FAILED",
        ))
        db.flush()


def resolve_sku_match(db: Session, detection, registry_cache=None):
    """Match only against approved exemplars; reuse one registry per model version."""
    if detection.embedding is None or not detection.embedding_model_version:
        return {"product_id": None, "status": "UNKNOWN", "similarity": None, "margin": None}
    try:
        cache = registry_cache if registry_cache is not None else {}
        version = detection.embedding_model_version
        if version not in cache:
            cache[version] = build_approved_product_registry(
                db,
                model_version=version,
                minimum_similarity=settings.product_matching_min_similarity,
                minimum_margin=settings.product_matching_min_margin,
            )
        match = cache[version].match(detection.embedding)
    except (ValueError, TypeError):
        logger.warning("SKU matching abstained: incompatible or invalid embedding registry")
        return {"product_id": None, "status": "UNKNOWN", "similarity": None, "margin": None}
    return {"product_id": match.product_id if match.status == "MATCHED" else None, "status": match.status, "similarity": match.similarity, "margin": match.margin}


def process_next_image(db: Session, provider, ocr_provider=None) -> int | None:
    image = (
        db.query(models.ShelfImage)
        .filter(models.ShelfImage.analysis_status == "PENDING", models.ShelfImage.retention_status == "ACTIVE")
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

        /* Linearize retention against derived processing: if restriction committed
           while inference was running, do not start OCR or persist any detections. */
        image = (
            db.query(models.ShelfImage)
            .filter(models.ShelfImage.id == image_id)
            .with_for_update()
            .first()
        )
        if image is None or image.retention_status != "ACTIVE":
            db.rollback()
            restricted_image = (
                db.query(models.ShelfImage)
                .filter(models.ShelfImage.id == image_id)
                .with_for_update()
                .first()
            )
            if restricted_image is not None:
                restricted_image.analysis_status = "FAILED"
                restricted_image.analysis_error = "Image restricted during processing"
                restricted_image.analysis_completed_at = models.utc_now()
                db.commit()
            logger.info("Skipped derived processing for restricted shelf image %s", image_id)
            return image_id

        for detection in result.detections:
            detection.validate_box()
        db.query(models.ShelfImageDetection).filter_by(shelf_image_id=image_id).delete()
        registry_cache = {}
        detection_rows = []
        for detection in result.detections:
            sku_match = resolve_sku_match(db, detection, registry_cache)
            row = models.ShelfImageDetection(
                shelf_image_id=image_id,
                product_id=sku_match["product_id"],
                label=detection.label,
                confidence=detection.confidence,
                x_min=detection.x_min,
                y_min=detection.y_min,
                x_max=detection.x_max,
                y_max=detection.y_max,
                model_version=result.model_version,
                embedding_model_version=detection.embedding_model_version,
                sku_match_status=sku_match["status"],
                sku_similarity=sku_match["similarity"],
                sku_match_margin=sku_match["margin"],
            )
            db.add(row)
            detection_rows.append(row)
        db.flush()
        if ocr_provider is not None:
            persist_ocr_evidence(db, image_id, image_path, detection_rows, ocr_provider)
            try:
                # Matching/fusion is isolated from both vision and OCR persistence.
                with db.begin_nested():
                    pipeline_counts = process_completed_ocr_run(db, image_id)
                    db.flush()
                logger.info("OCR pipeline completed for shelf image %s: %s", image_id, pipeline_counts)
            except Exception:
                logger.exception(
                    "OCR catalogue matching/fusion failed for shelf image %s; "
                    "visual detections and OCR regions are retained",
                    image_id,
                )
        image = (
            db.query(models.ShelfImage)
            .filter(models.ShelfImage.id == image_id)
            .with_for_update()
            .first()
        )
        if image is None or image.retention_status != "ACTIVE":
            db.rollback()
            restricted_image = (
                db.query(models.ShelfImage)
                .filter(models.ShelfImage.id == image_id)
                .with_for_update()
                .first()
            )
            if restricted_image is not None:
                restricted_image.analysis_status = "FAILED"
                restricted_image.analysis_error = "Image restricted during processing"
                restricted_image.analysis_completed_at = models.utc_now()
                db.commit()
            logger.info("Discarded inference output for restricted shelf image %s", image_id)
            return image_id
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

    try:
        ocr_provider = load_ocr_provider()
        if ocr_provider is not None:
            logger.info("Optional OCR provider enabled: %s", settings.ocr_provider_name)
    except Exception:
        logger.exception("Optional OCR provider could not be loaded; continuing with visual inference only")
        ocr_provider = None

    while True:
        db = SessionLocal()
        try:
            image_id = process_next_image(db, provider, ocr_provider=ocr_provider)
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
