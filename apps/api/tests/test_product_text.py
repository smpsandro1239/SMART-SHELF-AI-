import pytest

from app.product_text import (
    OCRText,
    normalize_product_text,
    rank_product_text_candidates,
)


def test_normalization_preserves_variant_words_and_pack_sizes():
    assert normalize_product_text("Coca-Cola ZERO 1,5 L") == "coca cola zero 1 5 l"


def test_exact_text_suggests_matching_product():
    result = rank_product_text_candidates(
        "Coca-Cola Zero 1.5L",
        [(1, "Coca-Cola Original 1.5L"), (2, "Coca-Cola Zero 1.5L")],
    )
    assert result.status == "SUGGESTED"
    assert result.product_id == 2


def test_close_text_candidates_are_ambiguous():
    result = rank_product_text_candidates(
        "Coca Cola 1.5L",
        [(1, "Coca Cola Original 1.5L"), (2, "Coca Cola Zero 1.5L")],
        minimum_score=0.5,
        minimum_margin=0.05,
    )
    assert result.status == "AMBIGUOUS"
    assert result.product_id is None


def test_unrelated_text_is_unknown():
    result = rank_product_text_candidates("shampoo repair", [(1, "Coca Cola Zero")])
    assert result.status == "UNKNOWN"


def test_invalid_ocr_confidence_and_empty_text_are_rejected():
    with pytest.raises(ValueError):
        OCRText("  ", 0.9)
    with pytest.raises(ValueError):
        OCRText("zero", 1.1)


def test_invalid_text_queries_are_rejected():
    with pytest.raises(ValueError):
        rank_product_text_candidates("!!!", [(1, "Coca Cola")])



def test_catalogue_name_match_is_not_penalized_when_optional_brand_is_missing():
    from app.product_text import CatalogueProduct, rank_product_catalogue_candidates

    result = rank_product_catalogue_candidates(
        "Leite Meio-Gordo 1 L",
        [
            CatalogueProduct(1, "LEITE-1L", "Leite Meio-Gordo 1 L", "Marca A", "1 L"),
            CatalogueProduct(2, "BEBIDA-1L", "Bebida de Aveia 1 L", "Marca B", "1 L"),
        ],
    )

    assert result.status == "SUGGESTED"
    assert result.product_id == 1
    assert result.score == 1.0


def test_catalogue_brand_is_used_as_positive_evidence_when_ocr_captures_it():
    from app.product_text import CatalogueProduct, rank_product_catalogue_candidates

    result = rank_product_catalogue_candidates(
        "Marca A Leite Meio-Gordo 1 L",
        [
            CatalogueProduct(1, "LEITE-1L", "Leite Meio-Gordo 1 L", "Marca A", "1 L"),
            CatalogueProduct(2, "LEITE-1L-B", "Leite Meio-Gordo 1 L", "Marca B", "1 L"),
        ],
    )

    assert result.status == "SUGGESTED"
    assert result.product_id == 1
    assert "brand_tokens_present" in result.candidates[0].reasons
