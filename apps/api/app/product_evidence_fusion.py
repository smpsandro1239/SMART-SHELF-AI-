"""Conservative fusion of visual SKU matching and OCR catalogue evidence.

The result is a review suggestion, never an automatic catalogue approval.
Visual cosine similarity and OCR string similarity are not treated as
comparable probabilities; fusion uses candidate identity and explicit states.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.product_matching import ProductMatch
from app.product_text import OCRText, TextMatch


@dataclass(frozen=True)
class FusedProductEvidence:
    status: str
    suggested_product_id: int | None
    visual_product_id: int | None
    text_product_id: int | None
    ocr_confidence: float | None
    reason: str


def fuse_product_evidence(
    visual: ProductMatch,
    text: TextMatch,
    ocr: OCRText | None,
    *,
    minimum_ocr_confidence: float = 0.65,
) -> FusedProductEvidence:
    """Fuse candidate identity without converting scores into probabilities.

    Statuses:
    - CONSENSUS: visual and sufficiently confident OCR agree.
    - VISUAL_ONLY: visual match exists; OCR is absent, weak or inconclusive.
    - TEXT_ONLY: OCR proposes a candidate but visual matching abstained.
    - CONFLICT: visual and sufficiently confident OCR propose different SKUs.
    - AMBIGUOUS: at least one useful signal is explicitly ambiguous.
    - UNKNOWN: neither signal supplies a usable candidate.
    """
    if not 0 <= minimum_ocr_confidence <= 1:
        raise ValueError("minimum_ocr_confidence must be between 0 and 1")
    if ocr is not None and not isinstance(ocr, OCRText):
        raise TypeError("ocr must be an OCRText instance or None")

    visual_id = visual.product_id if visual.status == "MATCHED" else None
    text_is_reliable = (
        ocr is not None
        and ocr.confidence >= minimum_ocr_confidence
        and text.status == "SUGGESTED"
    )
    text_id = text.product_id if text_is_reliable else None
    confidence = ocr.confidence if ocr is not None else None

    if visual_id is not None and text_id is not None:
        if visual_id == text_id:
            return FusedProductEvidence(
                "CONSENSUS", visual_id, visual_id, text_id, confidence,
                "Visual matching and sufficiently confident OCR propose the same SKU; human confirmation remains required.",
            )
        return FusedProductEvidence(
            "CONFLICT", None, visual_id, text_id, confidence,
            "Visual matching and OCR propose different SKUs; request human review.",
        )

    if visual.status == "AMBIGUOUS" or (text.status == "AMBIGUOUS" and ocr is not None and ocr.confidence >= minimum_ocr_confidence):
        return FusedProductEvidence(
            "AMBIGUOUS", None, visual_id, text_id, confidence,
            "At least one reliable evidence source has multiple close candidates.",
        )

    if visual_id is not None:
        return FusedProductEvidence(
            "VISUAL_ONLY", visual_id, visual_id, None, confidence,
            "Only visual matching supplied a decisive candidate; OCR was absent, weak or inconclusive.",
        )

    if text_id is not None:
        return FusedProductEvidence(
            "TEXT_ONLY", text_id, None, text_id, confidence,
            "OCR supplied a candidate but visual matching did not; verify manually.",
        )

    return FusedProductEvidence(
        "UNKNOWN", None, None, None, confidence,
        "No evidence source supplied a usable SKU candidate.",
    )
