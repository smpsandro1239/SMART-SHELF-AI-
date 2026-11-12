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
    """Load only approved, attributable exemplars for one embedding model.

    Pending/rejected rows and approvals without a surviving reviewer identity
    are intentionally excluded from operational matching.
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
        .order_by(models.ProductEmbeddingExemplar.product_id, models.ProductEmbeddingExemplar.id)
        .all()
    )
    exemplars = [
        ProductExemplar(
            product_id=row.product_id,
            embedding=tuple(row.embedding),
            model_version=row.model_version,
            image_sha256=row.image_sha256,
            reviewed_by=reviewer_email,
            reviewed_at=row.reviewed_at.isoformat(),
            licence=row.licence,
        )
        for row, reviewer_email in rows
    ]
    return ProductEmbeddingRegistry(
        exemplars,
        model_version=model_version,
        minimum_similarity=minimum_similarity,
        minimum_margin=minimum_margin,
    )
