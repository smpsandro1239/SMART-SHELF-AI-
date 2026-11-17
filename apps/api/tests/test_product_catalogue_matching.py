import pytest

from app.product_text import (
    CatalogueProduct,
    normalize_product_text,
    rank_product_catalogue_candidates,
)


def test_catalogue_match_explains_exact_sku_match():
    result = rank_product_catalogue_candidates(
        "78912345 Leite Meio Gordo 1 L",
        [
            CatalogueProduct(1, "111", "Leite Magro 1 L", "Marca A", "1 L"),
            CatalogueProduct(2, "78912345", "Leite Meio-Gordo 1 L", "Marca B", "1 L"),
        ],
    )

    assert result.status == "SUGGESTED"
    assert result.product_id == 2
    assert "exact_sku" in result.candidates[0].reasons


def test_catalogue_match_penalizes_conflicting_product_variant():
    result = rank_product_catalogue_candidates(
        "Coca Cola Zero 1.5 L",
        [
            CatalogueProduct(1, "100", "Coca Cola Original 1.5 L", "Coca Cola", "1.5 L"),
            CatalogueProduct(2, "200", "Coca Cola Zero 1.5 L", "Coca Cola", "1.5 L"),
        ],
    )

    assert result.status == "SUGGESTED"
    assert result.product_id == 2
    original = next(item for item in result.candidates if item.product_id == 1)
    assert "variant_conflict" in original.reasons
    assert result.candidates[0].score > original.score


def test_catalogue_match_does_not_suggest_unrelated_products():
    result = rank_product_catalogue_candidates(
        "detergente roupa lavanda",
        [CatalogueProduct(1, "123", "Leite Meio-Gordo 1 L", "Marca X", "1 L")],
    )

    assert result.status == "UNKNOWN"
    assert result.product_id is None


def test_close_catalogue_candidates_are_ambiguous():
    result = rank_product_catalogue_candidates(
        "Coca Cola 1.5 L",
        [
            CatalogueProduct(1, "100", "Coca Cola Original 1.5 L", "Coca Cola", "1.5 L"),
            CatalogueProduct(2, "200", "Coca Cola Zero 1.5 L", "Coca Cola", "1.5 L"),
        ],
        minimum_score=0.5,
        minimum_margin=0.2,
    )

    assert result.status == "AMBIGUOUS"
    assert result.product_id is None


def test_normalization_preserves_numbers_and_drops_accents():
    assert normalize_product_text("Água c/ Gás 1,5 L") == "agua c gas 1 5 l"


def test_invalid_catalogue_product_id_is_rejected():
    with pytest.raises(ValueError):
        rank_product_catalogue_candidates(
            "Produto",
            [CatalogueProduct(0, "A1", "Produto")],
        )
