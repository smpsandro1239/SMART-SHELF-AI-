"""Evaluation of production SKU suggestions against append-only human reviews.

Only the latest human decision per detection is used. The prediction is the
latest fused-evidence record available at the time of that decision, avoiding
leakage from later reprocessing. This module is read-only.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app import models


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def aggregate_reviewed_predictions(samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Calculate selective-classification metrics from independently reviewed cases."""
    rows = list(samples)
    known = [row for row in rows if row["expected_product_id"] is not None]
    unknown = [row for row in rows if row["expected_product_id"] is None]

    predicted = correct = incorrect_known = false_accepts = correct_abstentions = 0
    missed_known = 0
    statuses: Counter[str] = Counter()
    decisions: Counter[str] = Counter()
    models: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        expected = row["expected_product_id"]
        actual = row["predicted_product_id"]
        statuses[row["fusion_status"]] += 1
        decisions[row["review_decision"]] += 1
        models[row["model_version"] or "UNKNOWN_MODEL"].append(row)
        if actual is not None:
            predicted += 1
        if expected is not None:
            if actual == expected:
                correct += 1
            elif actual is None:
                missed_known += 1
            else:
                incorrect_known += 1
        elif actual is None:
            correct_abstentions += 1
        else:
            false_accepts += 1

    result = {
        "evaluation": "human-reviewed-sku-predictions-v1",
        "scope": "latest human review per detection; latest prediction available at review time",
        "sample_count": len(rows),
        "known_ground_truth_count": len(known),
        "unknown_ground_truth_count": len(unknown),
        "predicted_sku_count": predicted,
        "correct_matches": correct,
        "incorrect_known_matches": incorrect_known,
        "missed_known_products": missed_known,
        "false_accepts_on_rejected_detections": false_accepts,
        "correct_abstentions": correct_abstentions,
        "accuracy_including_abstentions": _ratio(correct + correct_abstentions, len(rows)),
        "precision_when_sku_predicted": _ratio(correct, predicted),
        "known_product_coverage": _ratio(predicted - false_accepts, len(known)),
        "known_product_correct_coverage": _ratio(correct, len(known)),
        "unknown_rejection_rate": _ratio(correct_abstentions, len(unknown)),
        "unknown_false_accept_rate": _ratio(false_accepts, len(unknown)),
        "fusion_status_breakdown": dict(sorted(statuses.items())),
        "human_decision_breakdown": dict(sorted(decisions.items())),
        "by_model_version": {},
        "warnings": [
            "Metrics cover reviewed detections only; unreviewed predictions are excluded.",
            "Human reviews are operational labels, not necessarily an independently sampled test set.",
            "Use store/session-separated data for formal model comparisons and retain an untouched test set.",
            "A rejected detection is treated as an unknown/non-product case, not as a missing SKU.",
            "This report is read-only and does not train models, approve exemplars or change inventory.",
        ],
    }
    for version, model_rows in sorted(models.items()):
        if version == "UNKNOWN_MODEL":
            continue
        sub = aggregate_reviewed_predictions(model_rows)
        result["by_model_version"][version] = {
            key: sub[key]
            for key in (
                "sample_count",
                "known_ground_truth_count",
                "unknown_ground_truth_count",
                "predicted_sku_count",
                "correct_matches",
                "incorrect_known_matches",
                "false_accepts_on_rejected_detections",
                "accuracy_including_abstentions",
                "precision_when_sku_predicted",
                "known_product_coverage",
                "known_product_correct_coverage",
                "unknown_rejection_rate",
                "unknown_false_accept_rate",
            )
        }
    return result


def build_reviewed_prediction_report(
    db: Session,
    *,
    store_id: int | None = None,
    model_version: str | None = None,
) -> dict[str, Any]:
    """Build a read-only report from the latest review and preceding fused prediction."""
    latest_review_id = (
        db.query(func.max(models.DetectionSkuReview.id))
        .filter(models.DetectionSkuReview.detection_id == models.ShelfImageDetection.id)
        .correlate(models.ShelfImageDetection)
        .scalar_subquery()
    )
    query = (
        db.query(
            models.DetectionSkuReview,
            models.ShelfImageFusedEvidence,
            models.ShelfImageDetection,
            models.ShelfImage,
            models.Shelf,
            models.Zone,
        )
        .join(
            models.ShelfImageDetection,
            models.DetectionSkuReview.detection_id == models.ShelfImageDetection.id,
        )
        .join(
            models.ShelfImage,
            models.ShelfImageDetection.shelf_image_id == models.ShelfImage.id,
        )
        .join(models.Shelf, models.ShelfImage.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .outerjoin(
            models.ShelfImageFusedEvidence,
            and_(
                models.ShelfImageFusedEvidence.detection_id == models.ShelfImageDetection.id,
                models.ShelfImageFusedEvidence.created_at <= models.DetectionSkuReview.created_at,
            ),
        )
        .filter(models.DetectionSkuReview.id == latest_review_id)
    )
    if store_id is not None:
        query = query.filter(models.Zone.store_id == store_id)

    selected: dict[int, tuple[Any, ...]] = {}
    review_ids: set[int] = set()
    for review, fused, detection, image, shelf, zone in query.all():
        review_ids.add(review.id)
        if model_version is not None:
            if fused is None or fused.visual_model_version != model_version:
                continue
        current = selected.get(detection.id)
        if current is None:
            selected[detection.id] = (review, fused, detection, image, shelf, zone)
        else:
            previous_fused = current[1]
            if fused is not None and (
                previous_fused is None
                or (fused.created_at, fused.id) > (previous_fused.created_at, previous_fused.id)
            ):
                selected[detection.id] = (review, fused, detection, image, shelf, zone)

    samples: list[dict[str, Any]] = []
    without_fusion = 0
    for review, fused, detection, image, shelf, zone in selected.values():
        if fused is None:
            without_fusion += 1
            continue
        samples.append({
            "expected_product_id": (
                None if review.decision == "REJECTED" else review.selected_product_id
            ),
            "predicted_product_id": fused.suggested_product_id,
            "fusion_status": fused.status,
            "review_decision": review.decision,
            "model_version": fused.visual_model_version or detection.embedding_model_version,
        })

    report = aggregate_reviewed_predictions(samples)
    report.update({
        "store_id": store_id,
        "model_version_filter": model_version,
        "latest_review_count": len(review_ids),
        "reviewed_detections_without_matching_fusion": without_fusion,
        "evaluated_at": models.utc_now().isoformat(),
    })
    return report
