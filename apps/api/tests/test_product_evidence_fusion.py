import pytest

from app.product_matching import ProductMatch, ProductCandidate
from app.product_text import OCRText, TextMatch, TextCandidate
from app.product_evidence_fusion import fuse_product_evidence


def visual(status, product_id=None):
    return ProductMatch(
        status=status,
        product_id=product_id,
        similarity=0.96 if product_id else None,
        margin=0.2 if product_id else None,
        candidates=(ProductCandidate(product_id, 0.96),) if product_id else (),
    )


def textual(status, product_id=None):
    return TextMatch(
        status=status,
        product_id=product_id,
        score=0.94 if product_id else None,
        margin=0.2 if product_id else None,
        candidates=(TextCandidate(product_id, 0.94),) if product_id else (),
    )


def test_visual_and_ocr_agreement_produces_consensus_not_approval():
    result = fuse_product_evidence(
        visual("MATCHED", 10), textual("SUGGESTED", 10), OCRText("Cola Zero", 0.9)
    )
    assert result.status == "CONSENSUS"
    assert result.suggested_product_id == 10
    assert "human confirmation" in result.reason


def test_disagreement_between_reliable_signals_is_conflict():
    result = fuse_product_evidence(
        visual("MATCHED", 10), textual("SUGGESTED", 20), OCRText("Cola Zero", 0.9)
    )
    assert result.status == "CONFLICT"
    assert result.suggested_product_id is None


def test_low_confidence_ocr_does_not_override_visual_match():
    result = fuse_product_evidence(
        visual("MATCHED", 10), textual("SUGGESTED", 20), OCRText("Cola Zero", 0.2)
    )
    assert result.status == "VISUAL_ONLY"
    assert result.suggested_product_id == 10


def test_ocr_alone_is_only_a_manual_review_suggestion():
    result = fuse_product_evidence(
        visual("UNKNOWN"), textual("SUGGESTED", 20), OCRText("Cola Zero", 0.95)
    )
    assert result.status == "TEXT_ONLY"
    assert result.suggested_product_id == 20


def test_ambiguous_visual_evidence_is_not_resolved_by_missing_ocr():
    result = fuse_product_evidence(
        visual("AMBIGUOUS"), textual("UNKNOWN"), None
    )
    assert result.status == "AMBIGUOUS"
    assert result.suggested_product_id is None


def test_no_useful_evidence_is_unknown():
    result = fuse_product_evidence(
        visual("UNKNOWN"), textual("UNKNOWN"), OCRText("unreadable label", 0.1)
    )
    assert result.status == "UNKNOWN"


def test_invalid_ocr_threshold_is_rejected():
    with pytest.raises(ValueError):
        fuse_product_evidence(visual("UNKNOWN"), textual("UNKNOWN"), None, minimum_ocr_confidence=1.1)
