"""Conservative SKU matching over provider-generated image embeddings.

This module deliberately does not generate embeddings or load model weights.
A vision provider supplies vectors; this registry compares them with reviewed
product exemplars and abstains whenever evidence is insufficient.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Iterable, Sequence


@dataclass(frozen=True)
class ProductExemplar:
    """Reviewed reference vector and its traceable origin."""

    product_id: int
    embedding: tuple[float, ...]
    model_version: str
    image_sha256: str
    reviewed_by: str
    reviewed_at: str
    licence: str

    def __post_init__(self) -> None:
        if self.product_id <= 0:
            raise ValueError("product_id must be positive")
        if not self.model_version.strip():
            raise ValueError("model_version is required")
        if len(self.image_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.image_sha256.lower()):
            raise ValueError("image_sha256 must be a 64-character hexadecimal digest")
        if not self.reviewed_by.strip() or not self.reviewed_at.strip() or not self.licence.strip():
            raise ValueError("reviewer, review timestamp and licence are required")
        _validated_vector(self.embedding)


@dataclass(frozen=True)
class ProductCandidate:
    product_id: int
    similarity: float


@dataclass(frozen=True)
class ProductMatch:
    status: str
    product_id: int | None
    similarity: float | None
    margin: float | None
    candidates: tuple[ProductCandidate, ...]


def _validated_vector(values: Sequence[float]) -> tuple[float, ...]:
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in values
    ):
        raise ValueError("embedding values must be numeric (booleans are not valid)")
    vector = tuple(float(value) for value in values)
    if not vector:
        raise ValueError("embedding cannot be empty")
    if any(not isfinite(value) for value in vector):
        raise ValueError("embedding values must be finite")
    if hypot(*vector) == 0:
        raise ValueError("embedding cannot be a zero vector")
    return vector


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    left_norm = hypot(*left)
    right_norm = hypot(*right)
    # Normalize before multiplying to avoid overflow for large but finite
    # provider values. Clamp rounding drift to the cosine domain.
    similarity = sum(
        (a / left_norm) * (b / right_norm)
        for a, b in zip(left, right)
    )
    return max(-1.0, min(1.0, similarity))


class ProductEmbeddingRegistry:
    """In-memory, provider-neutral registry with explicit abstention.

    Thresholds must be calibrated on a representative, store-relevant
    validation set before operational use. They are not universal constants.
    """

    def __init__(
        self,
        exemplars: Iterable[ProductExemplar],
        *,
        model_version: str,
        minimum_similarity: float = 0.90,
        minimum_margin: float = 0.05,
    ) -> None:
        if not model_version.strip():
            raise ValueError("model_version is required")
        if (
            isinstance(minimum_similarity, bool)
            or not isinstance(minimum_similarity, (int, float))
            or not isfinite(minimum_similarity)
            or not 0 <= minimum_similarity <= 1
        ):
            raise ValueError("minimum_similarity must be a finite number between 0 and 1")
        if (
            isinstance(minimum_margin, bool)
            or not isinstance(minimum_margin, (int, float))
            or not isfinite(minimum_margin)
            or not 0 <= minimum_margin <= 2
        ):
            raise ValueError("minimum_margin must be a finite number between 0 and 2")
        self.model_version = model_version.strip()
        self.minimum_similarity = minimum_similarity
        self.minimum_margin = minimum_margin
        self._exemplars = tuple(exemplars)
        if any(item.model_version != model_version for item in self._exemplars):
            raise ValueError("all exemplars must use the registry model_version")
        dimensions = {len(item.embedding) for item in self._exemplars}
        if len(dimensions) > 1:
            raise ValueError("all exemplar embeddings must have the same dimension")

    def match(self, embedding: Sequence[float], *, limit: int = 5) -> ProductMatch:
        if limit < 1:
            raise ValueError("limit must be positive")
        query = _validated_vector(embedding)
        if self._exemplars and len(query) != len(self._exemplars[0].embedding):
            raise ValueError("query embedding dimension does not match registry")

        # Keep the strongest exemplar per SKU; multiple photos must not make
        # one SKU occupy several positions and distort the ambiguity margin.
        best_by_product: dict[int, float] = {}
        for exemplar in self._exemplars:
            score = _cosine_similarity(query, exemplar.embedding)
            best_by_product[exemplar.product_id] = max(
                score, best_by_product.get(exemplar.product_id, -1.0)
            )
        ranked = sorted(
            (ProductCandidate(product_id, score) for product_id, score in best_by_product.items()),
            key=lambda candidate: (-candidate.similarity, candidate.product_id),
        )
        candidates = tuple(ranked[:limit])
        if not ranked or ranked[0].similarity < self.minimum_similarity:
            return ProductMatch("UNKNOWN", None, ranked[0].similarity if ranked else None, None, candidates)

        margin = ranked[0].similarity - (ranked[1].similarity if len(ranked) > 1 else -1.0)
        if len(ranked) > 1 and margin < self.minimum_margin:
            return ProductMatch("AMBIGUOUS", None, ranked[0].similarity, margin, candidates)

        return ProductMatch("MATCHED", ranked[0].product_id, ranked[0].similarity, margin, candidates)
