"""Offline evaluation and threshold sweep for few-shot SKU embeddings.

Input data must contain independently labelled query crops and approved,
attributable reference exemplars. This module never reads production tables,
changes catalogue records, or updates stock.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from app.product_matching import ProductEmbeddingRegistry, ProductExemplar


def _load_exemplars(raw: Any, model_version: str) -> list[ProductExemplar]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("exemplars must be a non-empty array")
    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"exemplars[{index}] must be an object")
        try:
            result.append(ProductExemplar(
                product_id=item["product_id"],
                embedding=tuple(item["embedding"]),
                model_version=item.get("model_version", model_version),
                image_sha256=item["image_sha256"],
                reviewed_by=item["reviewed_by"],
                reviewed_at=item["reviewed_at"],
                licence=item["licence"],
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid exemplar at index {index}: {exc}") from exc
    return result


def _validate_queries(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("queries must be a non-empty array")
    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or "embedding" not in item or "expected_product_id" not in item:
            raise ValueError(f"queries[{index}] requires embedding and expected_product_id")
        expected = item["expected_product_id"]
        if expected is not None and (
            isinstance(expected, bool) or not isinstance(expected, int) or expected <= 0
        ):
            raise ValueError(f"queries[{index}].expected_product_id must be a positive integer or null")
        if not isinstance(item["embedding"], list):
            raise ValueError(f"queries[{index}].embedding must be an array")
        result.append(item)
    return result


def evaluate_sku_matching(
    exemplars: Sequence[ProductExemplar],
    queries: Sequence[dict[str, Any]],
    *,
    similarity_thresholds: Sequence[float] = (0.80, 0.85, 0.90, 0.92, 0.95),
    margin_thresholds: Sequence[float] = (0.00, 0.03, 0.05, 0.08),
) -> dict[str, Any]:
    """Evaluate ranking and selective classification over a threshold grid.

    expected_product_id=null represents a product deliberately absent from
    the reference gallery. Split query images by store/session before calling.
    """
    if not exemplars or not queries:
        raise ValueError("At least one exemplar and one query are required")
    if not similarity_thresholds or not margin_thresholds:
        raise ValueError("Both threshold grids must be non-empty")
    for value in similarity_thresholds:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError("similarity thresholds must be between 0 and 1")
    for value in margin_thresholds:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 2:
            raise ValueError("margin thresholds must be between 0 and 2")

    model_versions = {item.model_version for item in exemplars}
    if len(model_versions) != 1:
        raise ValueError("Evaluation exemplars must use exactly one embedding model version")
    model_version = next(iter(model_versions))
    ranking_registry = ProductEmbeddingRegistry(
        exemplars, model_version=model_version, minimum_similarity=0.0, minimum_margin=0.0
    )

    known_queries = [item for item in queries if item["expected_product_id"] is not None]
    unknown_queries = [item for item in queries if item["expected_product_id"] is None]
    top1_correct = 0
    top1_available = 0
    for item in known_queries:
        candidates = ranking_registry.match(item["embedding"], limit=5).candidates
        if candidates:
            top1_available += 1
            top1_correct += candidates[0].product_id == item["expected_product_id"]

    operating_points = []
    for similarity in similarity_thresholds:
        for margin in margin_thresholds:
            registry = ProductEmbeddingRegistry(
                exemplars,
                model_version=model_version,
                minimum_similarity=float(similarity),
                minimum_margin=float(margin),
            )
            matched = correct = incorrect_known = 0
            accepted_unknown = unknown_rejected = ambiguous = rejected_unknown = 0
            for item in queries:
                result = registry.match(item["embedding"])
                expected = item["expected_product_id"]
                if result.status == "MATCHED":
                    matched += 1
                    if expected is None:
                        accepted_unknown += 1
                    elif result.product_id == expected:
                        correct += 1
                    else:
                        incorrect_known += 1
                elif result.status == "AMBIGUOUS":
                    ambiguous += 1
                    if expected is None:
                        unknown_rejected += 1
                else:
                    rejected_unknown += 1
                    if expected is None:
                        unknown_rejected += 1

            known_count = len(known_queries)
            unknown_count = len(unknown_queries)
            operating_points.append({
                "minimum_similarity": float(similarity),
                "minimum_margin": float(margin),
                "queries": len(queries),
                "known_queries": known_count,
                "unknown_queries": unknown_count,
                "matched": matched,
                "correct_matches": correct,
                "incorrect_known_matches": incorrect_known,
                "accepted_unknown_products": accepted_unknown,
                "ambiguous": ambiguous,
                "unknown": rejected_unknown,
                "precision_when_matched": round(correct / matched, 6) if matched else 0.0,
                "known_product_coverage": round((correct + incorrect_known) / known_count, 6) if known_count else None,
                "known_product_correct_coverage": round(correct / known_count, 6) if known_count else None,
                "unknown_rejection_rate": round(unknown_rejected / unknown_count, 6) if unknown_count else None,
                "unknown_false_accept_rate": round(accepted_unknown / unknown_count, 6) if unknown_count else None,
                "ambiguous_rate": round(ambiguous / len(queries), 6),
            })

    return {
        "evaluator": "smart-shelf-ai-sku-evaluation-v1",
        "model_version": model_version,
        "exemplar_count": len(exemplars),
        "sku_count": len({item.product_id for item in exemplars}),
        "query_count": len(queries),
        "known_query_count": len(known_queries),
        "unknown_query_count": len(unknown_queries),
        "top1_accuracy_known_before_abstention": round(top1_correct / top1_available, 6) if top1_available else None,
        "top1_evaluable_known_queries": top1_available,
        "operating_points": operating_points,
        "warnings": [
            "Results are only representative when query images are independent of reference images.",
            "Split by store, capture session or time period to prevent near-duplicate leakage.",
            "Unknown queries must represent realistic products absent from the gallery.",
            "Thresholds must be selected on validation data; keep a separate final test set untouched.",
            "This evaluator does not train models, approve exemplars, update products or alter stock.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate few-shot SKU embedding matching")
    parser.add_argument("--dataset", required=True, type=Path, help="JSON file with model_version, exemplars and queries")
    parser.add_argument("--output", type=Path, help="Optional path for the JSON report")
    args = parser.parse_args()
    try:
        document = json.loads(args.dataset.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or not isinstance(document.get("model_version"), str):
            raise ValueError("Dataset requires a model_version string")
        exemplars = _load_exemplars(document.get("exemplars"), document["model_version"])
        queries = _validate_queries(document.get("queries"))
        report = evaluate_sku_matching(exemplars, queries)
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
