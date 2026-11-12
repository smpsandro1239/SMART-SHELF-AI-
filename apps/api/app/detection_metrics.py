"""Provider-neutral object-detection evaluation against COCO ground truth.

Predictions use the COCO results shape: image_id, category_id, bbox [x,y,w,h],
score. AP uses 101-point interpolated precision at IoU thresholds 0.50:0.05:0.95.
Crowd annotations are excluded; this is a transparent project evaluator, not
a claim of bit-for-bit parity with the official COCO API.
"""
import argparse
import json
import math
from pathlib import Path
from typing import Any

from app.coco_dataset import validate_coco_document


def _valid_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _bbox(value: Any, label: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4 or not all(_valid_number(v) for v in value):
        raise ValueError(f"{label}.bbox must contain four finite numbers")
    x, y, width, height = map(float, value)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"{label}.bbox must have a non-negative origin and positive size")
    return x, y, width, height


def _iou(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    x1, y1 = max(lx, rx), max(ly, ry)
    x2, y2 = min(lx + lw, rx + rw), min(ly + lh, ry + rh)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = lw * lh + rw * rh - intersection
    return intersection / union if union > 0 else 0.0


def _average_precision(true_positives: list[int], false_positives: list[int], total_ground_truth: int) -> float:
    if total_ground_truth <= 0:
        return 0.0
    cumulative_tp = cumulative_fp = 0
    recalls: list[float] = []
    precisions: list[float] = []
    for tp, fp in zip(true_positives, false_positives):
        cumulative_tp += tp
        cumulative_fp += fp
        recalls.append(cumulative_tp / total_ground_truth)
        precisions.append(cumulative_tp / (cumulative_tp + cumulative_fp))
    interpolated = []
    for step in range(101):
        recall_level = step / 100
        candidates = [precision for recall, precision in zip(recalls, precisions) if recall >= recall_level]
        interpolated.append(max(candidates, default=0.0))
    return sum(interpolated) / 101


def _evaluate_class(
    ground_truth: dict[int, list[tuple[float, float, float, float]]],
    predictions: list[dict[str, Any]],
    iou_threshold: float,
    confidence_threshold: float,
) -> dict[str, Any]:
    total_gt = sum(len(items) for items in ground_truth.values())
    ordered = sorted(
        predictions,
        key=lambda item: (-item["score"], item["image_id"], item["_index"]),
    )
    matched: dict[int, set[int]] = {}
    true_positives: list[int] = []
    false_positives: list[int] = []
    for prediction in ordered:
        image_id = prediction["image_id"]
        candidates = ground_truth.get(image_id, [])
        used = matched.setdefault(image_id, set())
        best_index, best_iou = None, 0.0
        for index, target in enumerate(candidates):
            overlap = _iou(prediction["_bbox"], target)
            if index not in used and overlap > best_iou:
                best_index, best_iou = index, overlap
        if best_index is not None and best_iou >= iou_threshold:
            used.add(best_index)
            true_positives.append(1)
            false_positives.append(0)
        else:
            true_positives.append(0)
            false_positives.append(1)

    # AP uses the full ranked prediction list; confidence threshold must not
    # change mAP. Precision/recall below use only the selected operating point.
    selected_count = sum(item["score"] >= confidence_threshold for item in ordered)
    selected_tp = sum(true_positives[:selected_count])
    selected_fp = sum(false_positives[:selected_count])
    selected_fn = total_gt - selected_tp
    return {
        "ground_truth": total_gt,
        "predictions_at_confidence": selected_count,
        "true_positives": selected_tp,
        "false_positives": selected_fp,
        "false_negatives": selected_fn,
        "precision": selected_tp / (selected_tp + selected_fp) if selected_tp + selected_fp else 0.0,
        "recall": selected_tp / total_gt if total_gt else 0.0,
        "ap_101": _average_precision(true_positives, false_positives, total_gt),
    }

def evaluate_detections(
    ground_truth: Any,
    predictions: Any,
    *,
    confidence_threshold: float = 0.25,
    iou_thresholds: tuple[float, ...] = tuple(round(0.5 + step * 0.05, 2) for step in range(10)),
) -> dict[str, Any]:
    """Evaluate COCO-format predictions and return per-class and aggregate metrics."""
    errors = validate_coco_document(ground_truth)
    if errors:
        raise ValueError("Invalid COCO ground truth: " + "; ".join(errors[:10]))
    if not _valid_number(confidence_threshold) or not 0 <= confidence_threshold <= 1:
        raise ValueError("confidence_threshold must be between 0 and 1")
    if not isinstance(iou_thresholds, tuple) or not iou_thresholds:
        raise ValueError("iou_thresholds must be a non-empty tuple")
    if any(not _valid_number(value) or not 0 < value <= 1 for value in iou_thresholds):
        raise ValueError("IoU thresholds must be finite numbers in (0, 1]")
    if len(set(iou_thresholds)) != len(iou_thresholds):
        raise ValueError("IoU thresholds must be unique")
    if 0.5 not in iou_thresholds:
        raise ValueError("iou_thresholds must include 0.50 for precision/recall reporting")
    if not isinstance(predictions, list):
        raise ValueError("predictions must be a COCO results array")

    image_by_id = {item["id"]: item for item in ground_truth["images"]}
    category_by_id = {item["id"]: item["name"] for item in ground_truth["categories"]}
    gt_by_category: dict[int, dict[int, list[tuple[float, float, float, float]]]] = {
        category_id: {} for category_id in category_by_id
    }
    for annotation in ground_truth["annotations"]:
        if annotation.get("iscrowd", 0) == 1:
            continue
        category_id = annotation["category_id"]
        image_id = annotation["image_id"]
        gt_by_category[category_id].setdefault(image_id, []).append(
            tuple(map(float, annotation["bbox"]))
        )

    predictions_by_category: dict[int, list[dict[str, Any]]] = {
        category_id: [] for category_id in category_by_id
    }
    for index, item in enumerate(predictions):
        label = f"predictions[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object")
        image_id, category_id, score = item.get("image_id"), item.get("category_id"), item.get("score")
        if isinstance(image_id, bool) or not isinstance(image_id, int) or image_id not in image_by_id:
            raise ValueError(f"{label}.image_id references an unknown image")
        if isinstance(category_id, bool) or not isinstance(category_id, int) or category_id not in category_by_id:
            raise ValueError(f"{label}.category_id references an unknown category")
        if not _valid_number(score) or not 0 <= score <= 1:
            raise ValueError(f"{label}.score must be a finite number between 0 and 1")
        box = _bbox(item.get("bbox"), label)
        image = image_by_id[image_id]
        if box[0] + box[2] > image["width"] or box[1] + box[3] > image["height"]:
            raise ValueError(f"{label}.bbox exceeds image dimensions")
        predictions_by_category[category_id].append({
            "image_id": image_id,
            "score": float(score),
            "_bbox": box,
            "_index": index,
        })

    class_reports = {}
    valid_classes = []
    for category_id, category_name in sorted(category_by_id.items()):
        per_threshold = {
            str(threshold): _evaluate_class(
                gt_by_category[category_id],
                predictions_by_category[category_id],
                threshold,
                confidence_threshold,
            )
            for threshold in iou_thresholds
        }
        ap_values = [result["ap_101"] for result in per_threshold.values()]
        at_50 = per_threshold.get("0.5") or next(iter(per_threshold.values()))
        report = {
            "name": category_name,
            "ground_truth": sum(len(items) for items in gt_by_category[category_id].values()),
            "ap_by_iou": {key: round(value["ap_101"], 6) for key, value in per_threshold.items()},
            "map_50_95": round(sum(ap_values) / len(ap_values), 6),
            "precision_at_confidence": round(at_50["precision"], 6),
            "recall_at_confidence": round(at_50["recall"], 6),
            "counts_at_iou_50": {
                key: at_50[key]
                for key in ("predictions_at_confidence", "true_positives", "false_positives", "false_negatives")
            },
        }
        class_reports[str(category_id)] = report
        if report["ground_truth"] > 0:
            valid_classes.append(report)

    if not valid_classes:
        raise ValueError("Ground truth contains no non-crowd instances in any category")
    map50 = sum(item["ap_by_iou"].get("0.5", next(iter(item["ap_by_iou"].values()))) for item in valid_classes) / len(valid_classes)
    map5095 = sum(item["map_50_95"] for item in valid_classes) / len(valid_classes)
    # Include false positives from classes absent in ground truth in micro metrics.
    all_class_reports = list(class_reports.values())
    total_tp = sum(item["counts_at_iou_50"]["true_positives"] for item in all_class_reports)
    total_fp = sum(item["counts_at_iou_50"]["false_positives"] for item in all_class_reports)
    total_fn = sum(item["counts_at_iou_50"]["false_negatives"] for item in all_class_reports)
    return {
        "evaluator": "smart-shelf-ai-ap101-v1",
        "confidence_threshold": confidence_threshold,
        "iou_thresholds": list(iou_thresholds),
        "map_50": round(map50, 6),
        "map_50_95": round(map5095, 6),
        "precision_at_iou_50": round(total_tp / (total_tp + total_fp), 6) if total_tp + total_fp else 0.0,
        "recall_at_iou_50": round(total_tp / (total_tp + total_fn), 6) if total_tp + total_fn else 0.0,
        "counts_at_iou_50": {
            "true_positives": total_tp,
            "false_positives": total_fp,
            "false_negatives": total_fn,
        },
        "classes": class_reports,
        "limitations": [
            "101-point interpolated AP implementation; not guaranteed bit-for-bit identical to the official COCO evaluator.",
            "Crowd annotations (iscrowd=1) are excluded rather than matched using COCO crowd semantics.",
            "Precision and recall are reported at the configured confidence threshold and IoU 0.50.",
            "Metrics are meaningful only when ground-truth annotations are complete and independently reviewed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate COCO-format object detections")
    parser.add_argument("--ground-truth", required=True, type=Path, help="COCO annotations JSON")
    parser.add_argument("--predictions", required=True, type=Path, help="COCO results JSON array")
    parser.add_argument("--confidence-threshold", type=float, default=0.25)
    parser.add_argument("--output", type=Path, help="Optional JSON report output")
    args = parser.parse_args()
    try:
        ground_truth = json.loads(args.ground_truth.read_text(encoding="utf-8"))
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
        report = evaluate_detections(
            ground_truth, predictions, confidence_threshold=args.confidence_threshold
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: cannot write report: {exc}")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
