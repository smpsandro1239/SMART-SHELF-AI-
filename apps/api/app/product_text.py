"""Provider-neutral OCR text normalization and catalogue candidate ranking.

OCR is an auxiliary signal. A text match is never an automatic SKU approval.
No OCR engine or model is loaded by this module.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable


@dataclass(frozen=True)
class OCRText:
    text: str
    confidence: float

    def __post_init__(self):
        if not self.text.strip():
            raise ValueError("OCR text cannot be empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("OCR confidence must be between 0 and 1")


@dataclass(frozen=True)
class TextCandidate:
    product_id: int
    score: float


@dataclass(frozen=True)
class TextMatch:
    status: str
    product_id: int | None
    score: float | None
    margin: float | None
    candidates: tuple[TextCandidate, ...]


def normalize_product_text(value: str) -> str:
    """Normalize accents, case and punctuation while preserving digits."""
    if not isinstance(value, str):
        raise TypeError("Product text must be a string")
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", ascii_text))


def _similarity(observed: str, reference: str) -> float:
    left, right = normalize_product_text(observed), normalize_product_text(reference)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left, right).ratio()
    # Token overlap helps reorderings; sequence similarity helps OCR typos.
    return max(overlap, sequence)


def rank_product_text_candidates(
    observed_text: str,
    catalogue: Iterable[tuple[int, str]],
    *,
    minimum_score: float = 0.72,
    minimum_margin: float = 0.08,
    limit: int = 5,
) -> TextMatch:
    """Rank textual catalogue candidates and abstain on weak/close results."""
    if not 0 <= minimum_score <= 1:
        raise ValueError("minimum_score must be between 0 and 1")
    if not 0 <= minimum_margin <= 1:
        raise ValueError("minimum_margin must be between 0 and 1")
    if limit < 1:
        raise ValueError("limit must be positive")
    if not normalize_product_text(observed_text):
        raise ValueError("observed_text must contain letters or digits")

    best_by_product: dict[int, float] = {}
    for product_id, reference_text in catalogue:
        if isinstance(product_id, bool) or product_id <= 0:
            raise ValueError("catalogue product IDs must be positive integers")
        score = _similarity(observed_text, reference_text)
        best_by_product[product_id] = max(score, best_by_product.get(product_id, 0.0))
    ranked = sorted(
        (TextCandidate(product_id, score) for product_id, score in best_by_product.items()),
        key=lambda item: (-item.score, item.product_id),
    )
    candidates = tuple(ranked[:limit])
    if not ranked or ranked[0].score < minimum_score:
        return TextMatch("UNKNOWN", None, ranked[0].score if ranked else None, None, candidates)
    margin = ranked[0].score - ranked[1].score if len(ranked) > 1 else 1.0
    if len(ranked) > 1 and margin < minimum_margin:
        return TextMatch("AMBIGUOUS", None, ranked[0].score, margin, candidates)
    return TextMatch("SUGGESTED", ranked[0].product_id, ranked[0].score, margin, candidates)
