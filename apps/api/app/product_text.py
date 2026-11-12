"""Explainable OCR-to-catalogue matching with conservative abstention.

Scores are ranking signals, not calibrated probabilities. A suggestion always
requires human confirmation and never mutates Product or inventory records.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Sequence


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
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextMatch:
    status: str
    product_id: int | None
    score: float | None
    margin: float | None
    candidates: tuple[TextCandidate, ...]


@dataclass(frozen=True)
class CatalogueProduct:
    product_id: int
    sku: str
    name: str
    brand: str | None = None
    unit: str | None = None


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
    return max(overlap, sequence)


def _variant_markers(value: str) -> set[str]:
    """Return meaningful product-variant phrases, not generic words like 'sem'."""
    normalized = f" {normalize_product_text(value)} "
    markers = (
        "meio gordo", "sem lactose", "sem acucar", "sem gluten",
        "zero", "light", "diet", "original", "integral", "magro", "gordo",
    )
    found = {marker for marker in markers if f" {marker} " in normalized}
    if "meio gordo" in found:
        found.discard("gordo")
    return found


def _rank(
    scored: dict[int, tuple[float, set[str]]],
    *,
    minimum_score: float,
    minimum_margin: float,
    limit: int,
) -> TextMatch:
    ranked = sorted(
        (TextCandidate(pid, score, tuple(sorted(reasons))) for pid, (score, reasons) in scored.items()),
        key=lambda item: (-item.score, item.product_id),
    )
    candidates = tuple(ranked[:limit])
    if not ranked or ranked[0].score < minimum_score:
        return TextMatch("UNKNOWN", None, ranked[0].score if ranked else None, None, candidates)
    margin = ranked[0].score - ranked[1].score if len(ranked) > 1 else 1.0
    if len(ranked) > 1 and margin < minimum_margin:
        return TextMatch("AMBIGUOUS", None, ranked[0].score, margin, candidates)
    return TextMatch("SUGGESTED", ranked[0].product_id, ranked[0].score, margin, candidates)


def _validate_thresholds(minimum_score: float, minimum_margin: float, limit: int) -> None:
    if not 0 <= minimum_score <= 1:
        raise ValueError("minimum_score must be between 0 and 1")
    if not 0 <= minimum_margin <= 1:
        raise ValueError("minimum_margin must be between 0 and 1")
    if limit < 1:
        raise ValueError("limit must be positive")


def rank_product_text_candidates(
    observed_text: str,
    catalogue: Iterable[tuple[int, str]],
    *,
    minimum_score: float = 0.72,
    minimum_margin: float = 0.08,
    limit: int = 5,
) -> TextMatch:
    """Legacy name-only ranking retained for existing callers."""
    _validate_thresholds(minimum_score, minimum_margin, limit)
    if not normalize_product_text(observed_text):
        raise ValueError("observed_text must contain letters or digits")
    scored: dict[int, tuple[float, set[str]]] = {}
    for product_id, reference_text in catalogue:
        if isinstance(product_id, bool) or product_id <= 0:
            raise ValueError("catalogue product IDs must be positive integers")
        score = _similarity(observed_text, reference_text)
        reasons = {"name_similarity"} if score else set()
        previous = scored.get(product_id, (0.0, set()))
        scored[product_id] = (max(score, previous[0]), previous[1] | reasons)
    return _rank(scored, minimum_score=minimum_score, minimum_margin=minimum_margin, limit=limit)


def rank_product_catalogue_candidates(
    observed_text: str,
    catalogue: Iterable[CatalogueProduct],
    *,
    minimum_score: float = 0.68,
    minimum_margin: float = 0.10,
    limit: int = 5,
) -> TextMatch:
    """Rank active catalogue records using SKU, brand, name and package clues.

    Exact SKU matches receive a strong ranking signal. Conflicting variant or
    package-size tokens are penalized rather than silently ignored.
    """
    _validate_thresholds(minimum_score, minimum_margin, limit)
    observed = normalize_product_text(observed_text)
    if not observed:
        raise ValueError("observed_text must contain letters or digits")
    observed_tokens = set(observed.split())
    scored: dict[int, tuple[float, set[str]]] = {}

    for product in catalogue:
        if isinstance(product.product_id, bool) or product.product_id <= 0:
            raise ValueError("catalogue product IDs must be positive integers")
        sku = normalize_product_text(product.sku)
        name = normalize_product_text(product.name)
        brand = normalize_product_text(product.brand or "")
        unit = normalize_product_text(product.unit or "")
        searchable = " ".join(part for part in (name, brand, unit) if part)
        # Compare the observed label to the product name itself. Appending
        # optional brand/unit metadata here would penalize a perfect name read
        # whenever the OCR crop does not include those extra catalogue fields.
        name_score = _similarity(observed, name)
        brand_score = _similarity(observed, brand) if brand else 0.0
        reasons: set[str] = set()
        # Brand and unit are optional catalogue metadata. If OCR did not
        # capture the brand, do not lower an otherwise exact product-name
        # match. Only blend brand similarity when brand text is actually
        # present in the observed label.
        score = name_score
        brand_tokens = set(brand.split())
        observed_brand_tokens = brand_tokens & observed_tokens
        if brand and observed_brand_tokens:
            score = 0.78 * name_score + 0.22 * brand_score
            reasons.add("brand_similarity")
        if name_score:
            reasons.add("name_similarity")
        if brand and brand_tokens.issubset(observed_tokens):
            score = min(1.0, score + 0.08)
            reasons.add("brand_tokens_present")
        if sku and sku in observed_tokens:
            score = 1.0
            reasons.add("exact_sku")
        elif sku and len(sku) >= 4 and sku in observed:
            score = max(score, 0.96)
            reasons.add("sku_substring")

        # Variant phrases and pack-size values are meaningful discriminators.
        observed_variants = _variant_markers(observed)
        reference_variants = _variant_markers(" ".join((name, brand, unit)))
        if observed_variants and reference_variants and observed_variants.isdisjoint(reference_variants):
            score -= 0.18
            reasons.add("variant_conflict")
        observed_sizes = set(re.findall(r"\d+(?:[.,]\d+)?", observed))
        reference_sizes = set(re.findall(r"\d+(?:[.,]\d+)?", searchable))
        if observed_sizes and reference_sizes and observed_sizes.isdisjoint(reference_sizes):
            score -= 0.15
            reasons.add("pack_size_conflict")
        score = max(0.0, min(1.0, score))
        previous = scored.get(product.product_id, (0.0, set()))
        scored[product.product_id] = (max(score, previous[0]), previous[1] | reasons)

    return _rank(scored, minimum_score=minimum_score, minimum_margin=minimum_margin, limit=limit)
