"""Build a SKU matching registry from human-approved database exemplars."""

from sqlalchemy.orm import Session

from app import models
from app.product_matching import ProductEmbeddingRegistry, ProductExemplar



def lock_matching_source_images(
    db: Session,
    *,
    target_image_id: int,
    model_versions,
) -> None:
    """Lock target and approved exemplar source images in one stable ID order.

    The worker calls this after inference but before locking the target image for
    persistence. Acquiring the union in ascending primary-key order prevents two
    workers processing images that are also exemplars from deadlocking while
    each holds its target and waits for the other's source image.
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
            .filter(
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
    """Load approved exemplars and hold active source images against retention.

    Source-image rows are locked until the caller commits or rolls back. The
    retention endpoint takes the same row lock, so a restriction either wins
    before this query (and the exemplar is excluded) or waits until the current
    matching transaction finishes. Exemplars without a linked source image
    remain supported for explicitly licensed, externally supplied references.
    """
    rows = (
        db.query(models.ProductEmbeddingExemplar, models.User.email)
        .join(
            models.User,
            models.ProductEmbeddingExemplar.reviewed_by_user_id == models.User.id,
        )
        .filter(
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

    source_image_ids = sorted({
        exemplar.shelf_image_id
        for exemplar, _reviewer_email in rows
        if exemplar.shelf_image_id is not None
    })
    active_source_image_ids: set[int] = set()
    if source_image_ids:
        locked_source_images = (
            db.query(models.ShelfImage.id)
            .filter(
                models.ShelfImage.id.in_(source_image_ids),
                models.ShelfImage.retention_status == "ACTIVE",
            )
            .order_by(models.ShelfImage.id)
            .with_for_update()
            .all()
        )
        active_source_image_ids = {image_id for (image_id,) in locked_source_images}

    exemplars = [
        ProductExemplar(
            product_id=exemplar.product_id,
            embedding=tuple(exemplar.embedding),
            model_version=exemplar.model_version,
            image_sha256=exemplar.image_sha256,
            reviewed_by=reviewer_email,
            reviewed_at=exemplar.reviewed_at.isoformat(),
            licence=exemplar.licence,
        )
        for exemplar, reviewer_email in rows
        if exemplar.shelf_image_id is None
        or exemplar.shelf_image_id in active_source_image_ids
    ]
    return ProductEmbeddingRegistry(
        exemplars,
        model_version=model_version,
        minimum_similarity=minimum_similarity,
        minimum_margin=minimum_margin,
    )
