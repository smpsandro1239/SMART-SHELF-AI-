"""One-shot worker for pending shelf-image inference jobs.

A real provider is supplied through VISION_PROVIDER_FACTORY=module:factory.
No provider is enabled by default; pending images remain untouched.
"""
import argparse
import importlib
import logging
import os
import time
from datetime import timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app import models
from app.vision import VisionAnalysis, VisionProviderNotConfigured
from app.product_embedding_service import (
    build_approved_product_registry,
    lock_matching_source_images,
)
from app.product_ocr_association import associate_ocr_regions
from app.product_text import normalize_product_text
from app.product_pipeline import process_completed_ocr_run

logger = logging.getLogger("smart_shelf.vision_worker")


def load_provider():
    mode = settings.vision_provider_mode.strip().lower()
    if mode == "disabled":
        raise VisionProviderNotConfigured(
            "VISION_PROVIDER_MODE=disabled; configure an explicit mock or real provider before processing images."
        )
    if mode not in {"mock", "real"}:
        raise ValueError("VISION_PROVIDER_MODE must be disabled, mock or real")
    factory_path = settings.vision_provider_factory.strip()
    if not factory_path:
        raise VisionProviderNotConfigured(
            "VISION_PROVIDER_FACTORY is empty; configure the selected inference provider."
        )
    is_demo_factory = factory_path == "app.demo.vision:create_provider"
    if mode == "mock" and not is_demo_factory:
        raise ValueError("VISION_PROVIDER_MODE=mock only permits app.demo.vision:create_provider")
    if mode == "real" and is_demo_factory:
        raise ValueError("The deterministic demo provider cannot be loaded in real mode")
    if mode == "mock" and settings.app_env.lower() == "production":
        raise ValueError("Mock vision providers are forbidden in production")
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



def retry_failed_ocr_for_image(db: Session, image_id: int, provider) -> bool:
    """Retry only the latest failed OCR pass for an already analysed active image."""
    image = (
        db.query(models.ShelfImage)
        .filter(models.ShelfImage.id == image_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if (
        image is None
        or image.retention_status != "ACTIVE"
        or image.analysis_status != "COMPLETED"
    ):
        return False

    latest_run = (
        db.query(models.ShelfImageOCRRun)
        .filter(models.ShelfImageOCRRun.shelf_image_id == image_id)
        .order_by(models.ShelfImageOCRRun.id.desc())
        .first()
    )
    if latest_run is None or latest_run.status != "FAILED":
        return False

    detections = (
        db.query(models.ShelfImageDetection)
        .filter(models.ShelfImageDetection.shelf_image_id == image_id)
        .order_by(models.ShelfImageDetection.id.asc())
        .all()
    )
    image_path = _resolve_worker_image_path(db, image)
    persist_ocr_evidence(db, image_id, image_path, detections, provider)

    new_run = (
        db.query(models.ShelfImageOCRRun)
        .filter(
            models.ShelfImageOCRRun.shelf_image_id == image_id,
            models.ShelfImageOCRRun.id > latest_run.id,
        )
        .order_by(models.ShelfImageOCRRun.id.desc())
        .first()
    )
    if new_run is not None and new_run.status == "COMPLETED":
        try:
            with db.begin_nested():
                process_completed_ocr_run(db, image_id)
                db.flush()
        except Exception:
            logger.exception(
                "OCR matching/fusion retry failed for shelf image %s; OCR regions remain available",
                image_id,
            )

    # Recheck retention while holding the image row lock. The lock serializes
    # this commit with a concurrent restriction request.
    db.refresh(image)
    if image.retention_status != "ACTIVE":
        db.rollback()
        return False
    db.commit()
    return new_run is not None and new_run.status == "COMPLETED"

def resolve_sku_match(db: Session, detection, registry_cache=None, *, store_id: int | None = None):
    """Match only explicitly eligible object classes against approved exemplars."""
    allowed_labels = {
        label.strip()
        for label in settings.vision_sku_match_labels.split(",")
        if label.strip()
    }
    if detection.label not in allowed_labels:
        return {"product_id": None, "status": "UNKNOWN", "similarity": None, "margin": None}
    if detection.embedding is None or not detection.embedding_model_version:
        return {"product_id": None, "status": "UNKNOWN", "similarity": None, "margin": None}
    try:
        cache = registry_cache if registry_cache is not None else {}
        version = detection.embedding_model_version
        if version not in cache:
            cache[version] = build_approved_product_registry(
                db,
                model_version=version,
                store_id=store_id,
                minimum_similarity=settings.product_matching_min_similarity,
                minimum_margin=settings.product_matching_min_margin,
            )
        match = cache[version].match(detection.embedding)
    except (ValueError, TypeError):
        logger.warning("SKU matching abstained: incompatible or invalid embedding registry")
        return {"product_id": None, "status": "UNKNOWN", "similarity": None, "margin": None}
    return {"product_id": match.product_id if match.status == "MATCHED" else None, "status": match.status, "similarity": match.similarity, "margin": match.margin}


def _resolve_worker_image_path(db: Session, image: models.ShelfImage) -> Path:
    """Resolve a queued image only inside its owning store directory; reject symlinks."""
    store_id = (
        db.query(models.Zone.store_id)
        .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
        .join(models.ShelfImage, models.ShelfImage.shelf_id == models.Shelf.id)
        .filter(models.ShelfImage.id == image.id)
        .scalar()
    )
    if store_id is None:
        raise FileNotFoundError("Shelf image has no owning store")

    root = Path(settings.image_storage_path)
    if not root.is_absolute():
        root = Path.cwd() / root
    root = Path(os.path.abspath(root))
    store_root = root / str(store_id)
    candidate = Path(image.storage_path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = Path(os.path.abspath(candidate))

    try:
        relative_path = candidate.relative_to(store_root)
        store_root_resolved = store_root.resolve(strict=True)
        store_root_resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise FileNotFoundError("Stored image is outside its owning store directory") from exc

    cursor = store_root
    if cursor.is_symlink():
        raise FileNotFoundError("Store image directory cannot be a symlink")
    for part in relative_path.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise FileNotFoundError("Stored image path cannot contain symlinks")

    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(store_root_resolved)
    except (OSError, RuntimeError, ValueError) as exc:
        raise FileNotFoundError("Stored image path is unavailable or outside its store") from exc
    if not resolved.is_file():
        raise FileNotFoundError("Stored shelf image is not a regular file")
    return resolved


def requeue_stale_processing_images(
    db: Session,
    stale_after_seconds: int | None = None,
) -> int:
    """Return abandoned PROCESSING jobs to PENDING after a conservative lease timeout."""
    timeout = (
        settings.vision_processing_timeout_seconds
        if stale_after_seconds is None
        else stale_after_seconds
    )
    if timeout < 0:
        raise ValueError("stale_after_seconds must be non-negative")
    cutoff = models.utc_now() - timedelta(seconds=timeout)
    stale_images = (
        db.query(models.ShelfImage)
        .filter(
            models.ShelfImage.analysis_status == "PROCESSING",
            models.ShelfImage.retention_status == "ACTIVE",
            (
                models.ShelfImage.analysis_started_at.is_(None)
                | (models.ShelfImage.analysis_started_at < cutoff)
            ),
        )
        # Match the global source-image lock order used by embedding and retention
        # workflows; concurrent recovery workers must claim rows deterministically.
        .order_by(models.ShelfImage.id.asc())
        .with_for_update(skip_locked=True)
        .all()
    )
    for image in stale_images:
        image.analysis_status = "PENDING"
        image.analysis_error = "Recovered abandoned processing job after timeout"
        image.analysis_started_at = None
        image.analysis_completed_at = None
    if stale_images:
        db.commit()
        logger.warning("Requeued %s abandoned shelf-image jobs", len(stale_images))
    return len(stale_images)



def _same_claim_timestamp(current, claimed) -> bool:
    """Compare lease timestamps consistently across PostgreSQL and SQLite."""
    if current is None or claimed is None:
        return current is claimed
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if claimed.tzinfo is None:
        claimed = claimed.replace(tzinfo=timezone.utc)
    return current == claimed


def process_next_image(db: Session, provider, ocr_provider=None) -> int | None:
    requeue_stale_processing_images(db)
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
    image.analysis_status = "PROCESSING"
    image.analysis_error = None
    image.analysis_started_at = models.utc_now()
    image.analysis_completed_at = None
    db.commit()
    claimed_started_at = image.analysis_started_at

    try:
        image_path = _resolve_worker_image_path(db, image)
        result = VisionAnalysis.model_validate(provider.analyze(image_path))

        # Linearize retention against derived processing: if restriction committed
        # while inference was running, do not start OCR or persist any detections.
        store_id = lock_matching_source_images(
            db,
            target_image_id=image_id,
            model_versions={
                detection.embedding_model_version
                for detection in result.detections
                if detection.embedding is not None
                and detection.embedding_model_version
            },
        )
        release_guard = getattr(provider, "assert_release_current", None)
        if callable(release_guard):
            # Hold the persisted release row lock through output commit. A newer
            # release cannot become current between this check and persistence.
            release_guard(db)

        image = (
            db.query(models.ShelfImage)
            .filter(models.ShelfImage.id == image_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if (
            image is not None
            and (
                image.analysis_status != "PROCESSING"
                or not _same_claim_timestamp(image.analysis_started_at, claimed_started_at)
            )
        ):
            db.rollback()
            logger.info("Discarded stale inference result for shelf image %s; worker no longer owns the processing lease", image_id)
            return image_id
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
            sku_match = resolve_sku_match(
                db, detection, registry_cache, store_id=store_id
            )
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
            .populate_existing()
            .first()
        )
        if (
            image is not None
            and (
                image.analysis_status != "PROCESSING"
                or not _same_claim_timestamp(image.analysis_started_at, claimed_started_at)
            )
        ):
            db.rollback()
            logger.info("Discarded stale persisted output for shelf image %s; worker no longer owns the processing lease", image_id)
            return image_id
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
        image = (
            db.query(models.ShelfImage)
            .filter(models.ShelfImage.id == image_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if (
            image is not None
            and image.analysis_status == "PROCESSING"
            and _same_claim_timestamp(image.analysis_started_at, claimed_started_at)
        ):
            image.analysis_status = "FAILED"
            image.analysis_error = f"{type(exc).__name__}: processing failed"
            image.analysis_completed_at = models.utc_now()
            db.commit()
            logger.exception("Image analysis failed for shelf image %s", image_id)
        else:
            db.rollback()
            logger.warning(
                "Ignored failure for shelf image %s because the worker no longer owns its processing lease",
                image_id,
            )
    return image_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Process pending SMART SHELF AI image-analysis jobs")
    parser.add_argument("--once", action="store_true", help="Process at most one pending image and exit")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between queue checks")
    parser.add_argument(
        "--retry-failed-ocr-image-id",
        type=int,
        help="Retry OCR for one completed, active image without rerunning visual inference",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.retry_failed_ocr_image_id is not None:
        try:
            ocr_provider = load_ocr_provider()
        except Exception:
            logger.exception("OCR provider could not be loaded")
            return 2
        if ocr_provider is None:
            logger.error("OCR_PROVIDER_FACTORY is required for an OCR retry")
            return 2
        db = SessionLocal()
        try:
            retried = retry_failed_ocr_for_image(
                db, args.retry_failed_ocr_image_id, ocr_provider
            )
            return 0 if retried else 1
        finally:
            db.close()

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
