"""Build a SKU matching registry from human-approved database exemplars."""

from sqlalchemy.orm import Session

from app import models
from app.product_matching import ProductEmbeddingRegistry, ProductExemplar


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
