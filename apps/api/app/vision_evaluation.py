"""Deterministic COCO-style object-detection evaluation without training side effects."""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable


IOU_THRESHOLDS = tuple(round(value, 2) for value in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95))


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _xywh(value: Any, label: str) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f"{label} must be [x, y, width, height]")
    x, y, width, height = (_number(item, label) for item in value)
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"{label} must describe a positive box inside the image")
    return x, y, width, height


def _iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def _average_precision(true_positives: list[int], false_positives: list[int], total_ground_truth: int) -> float | None:
    if total_ground_truth == 0:
        return None
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
        interpolated.append(max(candidates) if candidates else 0.0)
    return sum(interpolated) / 101


def _match_predictions(
    predictions: list[dict[str, Any]],
    ground_truth_by_image: dict[int, list[tuple[float, float, float, float]]],
    iou_threshold: float,
) -> tuple[list[int], list[int], int, int]:
    matched: dict[int, set[int]] = defaultdict(set)
    true_positives: list[int] = []
    false_positives: list[int] = []
    tp = fp = 0
    for prediction in predictions:
        image_id = prediction["image_id"]
        candidates = ground_truth_by_image.get(image_id, [])
        best_index = None
        best_iou = -1.0
        for index, truth_box in enumerate(candidates):
            if index in matched[image_id]:
                continue
            overlap = _iou(prediction["bbox"], truth_box)
            if overlap > best_iou:
                best_iou = overlap
                best_index = index
        if best_index is not None and best_iou >= iou_threshold:
            matched[image_id].add(best_index)
            true_positives.append(1)
            false_positives.append(0)
            tp += 1
        else:
            true_positives.append(0)
            false_positives.append(1)
            fp += 1
    return true_positives, false_positives, tp, fp


def evaluate_coco_detections(
    ground_truth: dict[str, Any],
    predictions: Iterable[dict[str, Any]],
    *,
    operating_threshold: float = 0.25,
) -> dict[str, Any]:
    """Evaluate COCO xywh boxes using AP101 at IoU .50:.05:.95 and an operating point.

    Crowd annotations are rejected rather than silently counted as ordinary objects.
    Predictions use absolute pixel xywh boxes and confidence scores in [0, 1].
    """
    threshold = _number(operating_threshold, "operating_threshold")
    if not 0 <= threshold <= 1:
        raise ValueError("operating_threshold must be between 0 and 1")
    if not isinstance(ground_truth, dict):
        raise ValueError("ground_truth must be a COCO JSON object")

    images = ground_truth.get("images")
    annotations = ground_truth.get("annotations")
    categories = ground_truth.get("categories")
    if not all(isinstance(value, list) for value in (images, annotations, categories)):
        raise ValueError("COCO ground_truth must contain images, annotations and categories arrays")

    image_sizes: dict[int, tuple[int, int]] = {}
    for image in images:
        if not isinstance(image, dict):
            raise ValueError("COCO image entries must be objects")
        image_id = image.get("id")
        width, height = image.get("width"), image.get("height")
        if type(image_id) is not int or image_id < 0 or image_id in image_sizes:
            raise ValueError("COCO image IDs must be unique non-negative integers")
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
            raise ValueError(f"COCO image {image_id} has invalid dimensions")
        image_sizes[image_id] = (width, height)

    category_names: dict[int, str] = {}
    for category in categories:
        if not isinstance(category, dict):
            raise ValueError("COCO category entries must be objects")
        category_id, name = category.get("id"), category.get("name")
        if type(category_id) is not int or category_id < 0 or category_id in category_names:
            raise ValueError("COCO category IDs must be unique non-negative integers")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"COCO category {category_id} has an invalid name")
        category_names[category_id] = name.strip()
    if not category_names:
        raise ValueError("COCO categories cannot be empty")

    ground_truth_by_class: dict[int, dict[int, list[tuple[float, float, float, float]]]] = {
        category_id: defaultdict(list) for category_id in category_names
    }
    for annotation in annotations:
        if not isinstance(annotation, dict):
            raise ValueError("COCO annotation entries must be objects")
        image_id, category_id = annotation.get("image_id"), annotation.get("category_id")
        if image_id not in image_sizes or category_id not in category_names:
            raise ValueError("COCO annotation references an unknown image or category")
        if annotation.get("iscrowd", 0) != 0:
            raise ValueError("iscrowd annotations are not supported by evaluation v1")
        box = _xywh(annotation.get("bbox"), "ground-truth bbox")
        width, height = image_sizes[image_id]
        if box[0] + box[2] > width + 1e-6 or box[1] + box[3] > height + 1e-6:
            raise ValueError("ground-truth bbox exceeds image dimensions")
        ground_truth_by_class[category_id][image_id].append(box)

    normalized_predictions = []
    for index, prediction in enumerate(predictions):
        if not isinstance(prediction, dict):
            raise ValueError("prediction entries must be objects")
        image_id, category_id = prediction.get("image_id"), prediction.get("category_id")
        if type(image_id) is not int or image_id not in image_sizes:
            raise ValueError("prediction references an unknown image")
        if type(category_id) is not int or category_id not in category_names:
            raise ValueError("prediction references an unknown category")
        score = _number(prediction.get("score"), "prediction score")
        if not 0 <= score <= 1:
            raise ValueError("prediction score must be between 0 and 1")
        box = _xywh(prediction.get("bbox"), "prediction bbox")
        width, height = image_sizes[image_id]
        if box[0] + box[2] > width + 1e-6 or box[1] + box[3] > height + 1e-6:
            raise ValueError("prediction bbox exceeds image dimensions")
        normalized_predictions.append({
            "image_id": image_id,
            "category_id": category_id,
            "score": score,
            "bbox": box,
            "order": index,
        })

    per_class: dict[str, Any] = {}
    all_ap50 = []
    all_ap50_95 = []
    total_tp = total_fp = total_fn = 0
    total_predictions_at_threshold = 0

    for category_id, category_name in sorted(category_names.items()):
        class_predictions = sorted(
            (item for item in normalized_predictions if item["category_id"] == category_id),
            key=lambda item: (-item["score"], item["image_id"], item["order"]),
        )
        class_truth = ground_truth_by_class[category_id]
        total_gt = sum(len(boxes) for boxes in class_truth.values())
        ap_by_iou: dict[str, float | None] = {}
        for iou_threshold in IOU_THRESHOLDS:
            tp_flags, fp_flags, _, _ = _match_predictions(
                class_predictions, class_truth, iou_threshold
            )
            ap_by_iou[f"{iou_threshold:.2f}"] = _average_precision(tp_flags, fp_flags, total_gt)

        at_operating_point = [
            item for item in class_predictions if item["score"] >= threshold
        ]
        _, _, tp, fp = _match_predictions(at_operating_point, class_truth, 0.50)
        fn = total_gt - tp
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / total_gt if total_gt else None
        f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
        ap_values = [value for value in ap_by_iou.values() if value is not None]
        ap50 = ap_by_iou["0.50"]
        ap50_95 = sum(ap_values) / len(ap_values) if ap_values else None
        if ap50 is not None:
            all_ap50.append(ap50)
            all_ap50_95.append(ap50_95)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        total_predictions_at_threshold += len(at_operating_point)
        per_class[str(category_id)] = {
            "name": category_name,
            "ground_truth_count": total_gt,
            "prediction_count": len(class_predictions),
            "ap50": round(ap50, 6) if ap50 is not None else None,
            "ap50_95": round(ap50_95, 6) if ap50_95 is not None else None,
            "ap_by_iou": {
                key: round(value, 6) if value is not None else None
                for key, value in ap_by_iou.items()
            },
            "operating_point": {
                "confidence_threshold": threshold,
                "iou_threshold": 0.50,
                "true_positives": tp,
                "false_positives": fp,
                "false_negatives": fn,
                "precision": round(precision, 6) if precision is not None else None,
                "recall": round(recall, 6) if recall is not None else None,
                "f1": round(f1, 6) if f1 is not None else None,
            },
        }

    overall_precision = total_tp / (total_tp + total_fp) if total_tp + total_fp else None
    overall_recall = total_tp / (total_tp + total_fn) if total_tp + total_fn else None
    overall_f1 = (
        2 * overall_precision * overall_recall / (overall_precision + overall_recall)
        if overall_precision is not None and overall_recall is not None and overall_precision + overall_recall
        else None
    )
    return {
        "evaluation": "coco-object-detection-ap101-v1",
        "image_count": len(image_sizes),
        "annotation_count": len(annotations),
        "prediction_count": len(normalized_predictions),
        "evaluated_class_count": len(all_ap50),
        "iou_thresholds": list(IOU_THRESHOLDS),
        "mAP50": round(sum(all_ap50) / len(all_ap50), 6) if all_ap50 else None,
        "mAP50_95": round(sum(all_ap50_95) / len(all_ap50_95), 6) if all_ap50_95 else None,
        "operating_point": {
            "confidence_threshold": threshold,
            "iou_threshold": 0.50,
            "prediction_count": total_predictions_at_threshold,
            "true_positives": total_tp,
            "false_positives": total_fp,
            "false_negatives": total_fn,
            "precision": round(overall_precision, 6) if overall_precision is not None else None,
            "recall": round(overall_recall, 6) if overall_recall is not None else None,
            "f1": round(overall_f1, 6) if overall_f1 is not None else None,
        },
        "per_class": per_class,
        "limitations": [
            "COCO crowd annotations are rejected in v1 rather than silently treated as ordinary boxes.",
            "AP is computed with 101-point interpolated precision at IoU thresholds 0.50 to 0.95.",
            "Only classes with at least one ground-truth instance contribute to macro mAP.",
            "This report does not estimate stock quantity, product availability or business impact.",
        ],
    }
