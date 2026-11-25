from app.product_matching import ProductEmbeddingRegistry, ProductExemplar


def make_exemplar(product_id: int, vector: tuple[float, ...]) -> ProductExemplar:
    return ProductExemplar(
        product_id=product_id,
        embedding=vector,
        model_version="embed-v1",
        image_sha256=f"{product_id:064x}",
        reviewed_by="reviewer@example.test",
        reviewed_at="2026-11-16T00:00:00+00:00",
        licence="store-owned-reference-image",
    )


def test_equal_similarity_candidates_are_ordered_by_product_id():
    registry = ProductEmbeddingRegistry(
        [
            make_exemplar(20, (1.0, 0.0)),
            make_exemplar(10, (1.0, 0.0)),
        ],
        model_version="embed-v1",
        minimum_similarity=0.9,
        minimum_margin=0.0,
    )

    result = registry.match((1.0, 0.0))

    assert result.status == "MATCHED"
    assert result.product_id == 10
    assert [candidate.product_id for candidate in result.candidates] == [10, 20]


def test_candidate_limit_does_not_hide_ambiguity_from_decision():
    registry = ProductEmbeddingRegistry(
        [
            make_exemplar(10, (1.0, 0.0)),
            make_exemplar(20, (1.0, 0.0)),
        ],
        model_version="embed-v1",
        minimum_similarity=0.9,
        minimum_margin=0.05,
    )

    result = registry.match((1.0, 0.0), limit=1)

    assert result.status == "AMBIGUOUS"
    assert result.product_id is None
    assert len(result.candidates) == 1
    assert result.candidates[0].product_id == 10


def test_candidate_limit_must_be_positive():
    registry = ProductEmbeddingRegistry([], model_version="embed-v1")

    for invalid_limit in (0, -1):
        try:
            registry.match((1.0, 0.0), limit=invalid_limit)
        except ValueError as exc:
            assert "limit must be positive" in str(exc)
        else:
            raise AssertionError("A non-positive candidate limit must be rejected")
