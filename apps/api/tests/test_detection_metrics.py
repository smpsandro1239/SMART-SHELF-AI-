import copy

import pytest

from app.detection_metrics import evaluate_detections


def ground_truth():
    return {
        "images": [{"id": 1, "file_name": "one.jpg", "width": 100, "height": 100},
                   {"id": 2, "file_name": "two.jpg", "width": 100, "height": 100}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 0, "bbox": [10, 10, 20, 20], "area": 400, "iscrowd": 0},
            {"id": 2, "image_id": 2, "category_id": 0, "bbox": [50, 50, 20, 20], "area": 400, "iscrowd": 0},
            {"id": 3, "image_id": 1, "category_id": 1, "bbox": [60, 10, 10, 10], "area": 100, "iscrowd": 0},
        ],
        "categories": [{"id": 0, "name": "product"}, {"id": 1, "name": "empty_space"}],
    }


def test_perfect_predictions_produce_perfect_map_and_precision_recall():
    predictions = [
        {"image_id": 1, "category_id": 0, "bbox": [10, 10, 20, 20], "score": 0.99},
        {"image_id": 2, "category_id": 0, "bbox": [50, 50, 20, 20], "score": 0.98},
        {"image_id": 1, "category_id": 1, "bbox": [60, 10, 10, 10], "score": 0.97},
    ]

    report = evaluate_detections(ground_truth(), predictions)

    assert report["map_50"] == 1.0
    assert report["map_50_95"] == 1.0
    assert report["precision_at_iou_50"] == 1.0
    assert report["recall_at_iou_50"] == 1.0
    assert report["counts_at_iou_50"] == {
        "true_positives": 3, "false_positives": 0, "false_negatives": 0
    }


def test_duplicate_prediction_counts_as_false_positive():
    predictions = [
        {"image_id": 1, "category_id": 0, "bbox": [10, 10, 20, 20], "score": 0.99},
        {"image_id": 1, "category_id": 0, "bbox": [10, 10, 20, 20], "score": 0.90},
    ]
    report = evaluate_detections(ground_truth(), predictions)
    assert report["classes"]["0"]["counts_at_iou_50"]["true_positives"] == 1
    assert report["classes"]["0"]["counts_at_iou_50"]["false_positives"] == 1
    assert report["classes"]["0"]["counts_at_iou_50"]["false_negatives"] == 1


def test_confidence_threshold_changes_precision_recall_counts():
    predictions = [
        {"image_id": 1, "category_id": 0, "bbox": [10, 10, 20, 20], "score": 0.9},
        {"image_id": 2, "category_id": 0, "bbox": [0, 0, 10, 10], "score": 0.1},
    ]
    report = evaluate_detections(ground_truth(), predictions, confidence_threshold=0.5)
    assert report["classes"]["0"]["counts_at_iou_50"]["predictions_at_confidence"] == 1
    assert report["classes"]["0"]["recall_at_confidence"] == 0.5


def test_unknown_image_category_and_invalid_boxes_are_rejected():
    valid = {"image_id": 99, "category_id": 0, "bbox": [1, 1, 2, 2], "score": 0.9}
    with pytest.raises(ValueError, match="unknown image"):
        evaluate_detections(ground_truth(), [valid])
    valid["image_id"] = 1
    valid["category_id"] = 99
    with pytest.raises(ValueError, match="unknown category"):
        evaluate_detections(ground_truth(), [valid])
    valid["category_id"] = 0
    valid["bbox"] = [1, 1, -2, 2]
    with pytest.raises(ValueError, match="positive size"):
        evaluate_detections(ground_truth(), [valid])


def test_invalid_scores_and_confidence_threshold_are_rejected():
    prediction = {"image_id": 1, "category_id": 0, "bbox": [10, 10, 20, 20], "score": float("nan")}
    with pytest.raises(ValueError, match="score"):
        evaluate_detections(ground_truth(), [prediction])
    with pytest.raises(ValueError, match="confidence_threshold"):
        evaluate_detections(ground_truth(), [], confidence_threshold=1.1)


def test_crowd_ground_truth_is_excluded_from_evaluation():
    document = ground_truth()
    document["annotations"][0]["iscrowd"] = 1
    predictions = [{"image_id": 1, "category_id": 0, "bbox": [10, 10, 20, 20], "score": 0.99}]
    report = evaluate_detections(document, predictions)
    assert report["classes"]["0"]["ground_truth"] == 1


def test_predictions_for_class_without_ground_truth_are_reported_as_false_positives():
    document = ground_truth()
    document["annotations"] = [item for item in document["annotations"] if item["category_id"] == 0]
    predictions = [{"image_id": 1, "category_id": 1, "bbox": [60, 10, 10, 10], "score": 0.99}]
    report = evaluate_detections(document, predictions)
    assert report["classes"]["1"]["ground_truth"] == 0
    assert report["classes"]["1"]["counts_at_iou_50"]["false_positives"] == 1
