import pytest

from app.product_matching import ProductExemplar
from app.sku_matching_evaluation import evaluate_sku_matching


def exemplar(product_id, vector, digest):
    return ProductExemplar(
        product_id=product_id,
        embedding=tuple(vector),
        model_version="dinov2-small-v1",
        image_sha256=digest * 64,
        reviewed_by="reviewer@example.test",
        reviewed_at="2026-01-15T10:00:00Z",
        licence="store-owned-reference-image",
    )


def test_evaluator_reports_known_accuracy_and_unknown_rejection():
    exemplars = [
        exemplar(1, [1.0, 0.0], "a"),
        exemplar(2, [0.0, 1.0], "b"),
    ]
    queries = [
        {"embedding": [0.99, 0.01], "expected_product_id": 1},
        {"embedding": [0.01, 0.99], "expected_product_id": 2},
        {"embedding": [-1.0, 0.0], "expected_product_id": None},
    ]

    report = evaluate_sku_matching(
        exemplars,
        queries,
        similarity_thresholds=[0.80, 0.95],
        margin_thresholds=[0.05],
    )

    assert report["top1_accuracy_known_before_abstention"] == 1.0
    assert report["known_query_count"] == 2
    assert report["unknown_query_count"] == 1
    low = report["operating_points"][0]
    high = report["operating_points"][1]
    assert low["precision_when_matched"] == 1.0
    assert low["unknown_rejection_rate"] == 1.0
    assert high["known_product_coverage"] == 0.0


def test_evaluator_exposes_unknown_false_accepts():
    exemplars = [exemplar(1, [1.0, 0.0], "c")]
    queries = [
        {"embedding": [1.0, 0.0], "expected_product_id": 1},
        {"embedding": [1.0, 0.0], "expected_product_id": None},
    ]

    report = evaluate_sku_matching(
        exemplars,
        queries,
        similarity_thresholds=[0.80],
        margin_thresholds=[0.05],
    )

    point = report["operating_points"][0]
    assert point["unknown_false_accept_rate"] == 1.0
    assert point["unknown_rejection_rate"] == 0.0
    assert point["incorrect_known_matches"] == 0


def test_evaluator_rejects_mixed_embedding_versions():
    with pytest.raises(ValueError, match="exactly one"):
        evaluate_sku_matching(
            [exemplar(1, [1.0, 0.0], "d"), ProductExemplar(
                product_id=2,
                embedding=(0.0, 1.0),
                model_version="other-version",
                image_sha256="e" * 64,
                reviewed_by="reviewer@example.test",
                reviewed_at="2026-01-15T10:00:00Z",
                licence="store-owned-reference-image",
            )],
            [{"embedding": [1.0, 0.0], "expected_product_id": 1}],
        )


def test_evaluator_requires_nonempty_queries_and_thresholds():
    exemplar_row = exemplar(1, [1.0, 0.0], "f")
    with pytest.raises(ValueError, match="At least one"):
        evaluate_sku_matching([exemplar_row], [])
    with pytest.raises(ValueError, match="non-empty"):
        evaluate_sku_matching(
            [exemplar_row],
            [{"embedding": [1.0, 0.0], "expected_product_id": 1}],
            similarity_thresholds=[],
        )
