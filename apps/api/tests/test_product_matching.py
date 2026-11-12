import pytest

from app.product_matching import ProductEmbeddingRegistry, ProductExemplar


def exemplar(product_id, vector, *, digest=None):
    return ProductExemplar(
        product_id=product_id,
        embedding=tuple(vector),
        model_version="embed-v1",
        image_sha256=digest or (f"{product_id:064x}"),
        reviewed_by="reviewer@example.test",
        reviewed_at="2026-01-15T10:00:00Z",
        licence="store-owned-reference-image",
    )


def test_registry_accepts_clear_sku_match():
    registry = ProductEmbeddingRegistry(
        [exemplar(10, [1, 0]), exemplar(20, [0, 1])],
        model_version="embed-v1",
        minimum_similarity=0.90,
        minimum_margin=0.10,
    )

    result = registry.match([0.99, 0.01])

    assert result.status == "MATCHED"
    assert result.product_id == 10
    assert result.similarity > 0.99


def test_registry_abstains_when_similarity_is_too_low():
    registry = ProductEmbeddingRegistry(
        [exemplar(10, [1, 0])],
        model_version="embed-v1",
        minimum_similarity=0.95,
    )

    result = registry.match([0, 1])

    assert result.status == "UNKNOWN"
    assert result.product_id is None


def test_registry_abstains_when_top_candidates_are_too_close():
    registry = ProductEmbeddingRegistry(
        [exemplar(10, [1, 0]), exemplar(20, [0.99, 0.1])],
        model_version="embed-v1",
        minimum_similarity=0.80,
        minimum_margin=0.05,
    )

    result = registry.match([1, 0])

    assert result.status == "AMBIGUOUS"
    assert result.product_id is None
    assert result.margin < 0.05


def test_multiple_exemplars_of_same_sku_do_not_fake_margin():
    registry = ProductEmbeddingRegistry(
        [
            exemplar(10, [1, 0]),
            exemplar(10, [0.99, 0.01], digest="a" * 64),
            exemplar(20, [0, 1]),
        ],
        model_version="embed-v1",
        minimum_similarity=0.80,
        minimum_margin=0.05,
    )

    result = registry.match([1, 0])

    assert result.status == "MATCHED"
    assert result.product_id == 10
    assert len(result.candidates) == 2


@pytest.mark.parametrize("vector", [[], [0, 0], [float("nan"), 1], [float("inf"), 1]])
def test_registry_rejects_invalid_query_vectors(vector):
    registry = ProductEmbeddingRegistry([], model_version="embed-v1")
    with pytest.raises(ValueError):
        registry.match(vector)


def test_registry_rejects_incompatible_model_versions():
    with pytest.raises(ValueError, match="model_version"):
        ProductEmbeddingRegistry(
            [exemplar(10, [1, 0])],
            model_version="different-model",
        )


def test_registry_rejects_invalid_exemplar_provenance():
    with pytest.raises(ValueError, match="licence"):
        ProductExemplar(
            product_id=1,
            embedding=(1.0, 0.0),
            model_version="embed-v1",
            image_sha256="a" * 64,
            reviewed_by="reviewer",
            reviewed_at="2026-01-15T10:00:00Z",
            licence="",
        )


def test_registry_rejects_dimension_mismatch():
    registry = ProductEmbeddingRegistry(
        [exemplar(10, [1, 0])],
        model_version="embed-v1",
    )
    with pytest.raises(ValueError, match="dimension"):
        registry.match([1, 0, 0])
