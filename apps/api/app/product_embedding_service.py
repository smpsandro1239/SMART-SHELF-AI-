"""Build a SKU matching registry from human-approved database exemplars."""

import logging

from sqlalchemy.orm import Session

from app import models
from app.product_matching import ProductEmbeddingRegistry, ProductExemplar

logger = logging.getLogger(__name__)


def lock_matching_source_images(
    db: Session,
    *,
    target_image_id: int,
    model_versions,
) -> None:
    """Lock target and approved exemplar source images in one stable ID order.

    The worker acquires this image lock set before loading the registry. All
    paths that need more than one resource use the global order
    source-image -> product -> exemplar. Sorting each resource class prevents
    two workers from taking the same rows in opposite orders.
    """
    versions = sorted({version for version in model_versions if version})
    image_ids = {target_image_id}
    if versions:
        source_rows = (
            db.query(models.ProductEmbeddingExemplar.shelf_image_id)
            .join(
                models.User,
                models.ProductEmbeddingExemplar.reviewed_by_user_id == models.User.id,
            )
            .join(
                models.Product,
                models.ProductEmbeddingExemplar.product_id == models.Product.id,
            )
            .filter(
                models.Product.is_active.is_(True),
                models.ProductEmbeddingExemplar.review_status == "APPROVED",
                models.ProductEmbeddingExemplar.model_version.in_(versions),
                models.ProductEmbeddingExemplar.reviewed_at.is_not(None),
                models.ProductEmbeddingExemplar.shelf_image_id.is_not(None),
            )
            .distinct()
            .all()
        )
        image_ids.update(image_id for (image_id,) in source_rows)

    (
        db.query(models.ShelfImage.id)
        .filter(models.ShelfImage.id.in_(sorted(image_ids)))
        .order_by(models.ShelfImage.id)
        .with_for_update()
        .all()
    )


def build_approved_product_registry(
    db: Session,
    *,
    model_version: str,
    minimum_similarity: float = 0.90,
    minimum_margin: float = 0.05,
) -> ProductEmbeddingRegistry:
    """Load approved exemplars while serializing against review and retention.

    Lock acquisition follows the shared order: source images by ID, products
    by ID, then exemplars by ID. The initial candidate read is deliberately
    unlocked; every eligibility decision is repeated after the corresponding
    rows have been locked. Locks remain held until the caller commits or rolls
    back, so a concurrent retention/review cannot invalidate the registry
    between validation and use.
    """
    model_version = model_version.strip()
    if not model_version:
        raise ValueError("model_version is required")

    candidates = (
        db.query(
            models.ProductEmbeddingExemplar.id,
            models.ProductEmbeddingExemplar.product_id,
            models.ProductEmbeddingExemplar.shelf_image_id,
        )
        .join(
            models.Product,
            models.ProductEmbeddingExemplar.product_id == models.Product.id,
        )
        .filter(
            models.Product.is_active.is_(True),
            models.ProductEmbeddingExemplar.review_status == "APPROVED",
            models.ProductEmbeddingExemplar.model_version == model_version,
            models.ProductEmbeddingExemplar.reviewed_at.is_not(None),
        )
        .order_by(
            models.ProductEmbeddingExemplar.product_id,
            models.ProductEmbeddingExemplar.id,
        )
        .all()
    )

    if not candidates:
        return ProductEmbeddingRegistry(
            (),
            model_version=model_version,
            minimum_similarity=minimum_similarity,
            minimum_margin=minimum_margin,
        )

    source_image_ids = sorted({
        shelf_image_id
        for _exemplar_id, _product_id, shelf_image_id in candidates
        if shelf_image_id is not None
    })
    active_source_image_hashes: dict[int, str] = {}
    if source_image_ids:
        source_images = (
            db.query(models.ShelfImage)
            .filter(models.ShelfImage.id.in_(source_image_ids))
            .order_by(models.ShelfImage.id)
            .with_for_update()
            .populate_existing()
            .all()
        )
        active_source_image_hashes = {
            image.id: image.sha256.lower()
            for image in source_images
            if image.retention_status == "ACTIVE" and image.sha256
        }

    product_ids = sorted({product_id for _eid, product_id, _sid in candidates})
    (
        db.query(models.Product.id)
        .filter(models.Product.id.in_(product_ids))
        .order_by(models.Product.id)
        .with_for_update()
        .all()
    )

    candidate_ids = [exemplar_id for exemplar_id, _pid, _sid in candidates]
    rows = (
        db.query(models.ProductEmbeddingExemplar, models.User.email)
        .join(
            models.User,
            models.ProductEmbeddingExemplar.reviewed_by_user_id == models.User.id,
        )
        .join(
            models.Product,
            models.ProductEmbeddingExemplar.product_id == models.Product.id,
        )
        .filter(
            models.ProductEmbeddingExemplar.id.in_(candidate_ids),
            models.Product.is_active.is_(True),
            models.ProductEmbeddingExemplar.review_status == "APPROVED",
            models.ProductEmbeddingExemplar.model_version == model_version,
            models.ProductEmbeddingExemplar.reviewed_at.is_not(None),
        )
        .order_by(
            models.ProductEmbeddingExemplar.product_id,
            models.ProductEmbeddingExemplar.id,
        )
        .with_for_update(of=models.ProductEmbeddingExemplar)
        .populate_existing()
        .all()
    )

    exemplars = []
    for exemplar, reviewer_email in rows:
        if exemplar.shelf_image_id is not None:
            current_source_hash = active_source_image_hashes.get(exemplar.shelf_image_id)
            if (
                current_source_hash is None
                or not exemplar.image_sha256
                or exemplar.image_sha256.lower() != current_source_hash
            ):
                logger.warning(
                    "Skipping embedding exemplar id=%s: source image is missing, inactive, or has changed SHA-256",
                    exemplar.id,
                )
                continue

        # JSON columns do not enforce vector shape or finiteness. Treat legacy
        # or manually-corrupted rows as ineligible rather than failing the
        # entire registry (or allowing inconsistent metadata into matching).
        try:
            vector = tuple(exemplar.embedding)
            if (
                exemplar.embedding_dimension != len(vector)
                or not vector
                or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                       for value in vector)
            ):
                raise ValueError("stored embedding dimension or values are invalid")
            exemplars.append(
                ProductExemplar(
                    product_id=exemplar.product_id,
                    embedding=vector,
                    model_version=exemplar.model_version,
                    image_sha256=exemplar.image_sha256,
                    reviewed_by=reviewer_email,
                    reviewed_at=exemplar.reviewed_at.isoformat(),
                    licence=exemplar.licence,
                )
            )
        except (TypeError, ValueError, OverflowError) as exc:
            logger.warning(
                "Skipping invalid approved embedding exemplar id=%s: %s",
                exemplar.id,
                exc,
            )
    dimensions = {len(item.embedding) for item in exemplars}
    if len(dimensions) > 1:
        # A model version is a contract: all vectors produced by that exact
        # version must have one dimension. Do not pick a majority dimension,
        # because that could silently hide a corrupted cohort and bias matches.
        logger.error(
            "No SKU embeddings loaded for model_version=%s: conflicting dimensions=%s",
            model_version,
            sorted(dimensions),
        )
        exemplars = []

    return ProductEmbeddingRegistry(
        exemplars,
        model_version=model_version,
        minimum_similarity=minimum_similarity,
        minimum_margin=minimum_margin,
    )
