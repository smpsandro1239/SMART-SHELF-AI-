import pytest

from app.vision_evaluation import evaluate_coco_detections


def make_coco():
    return {
        "images": [{"id": 1, "file_name": "test/shelf-01.jpg", "width": 100, "height": 100}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 30, 40], "area": 1200, "iscrowd": 0}
        ],
        "categories": [{"id": 1, "name": "product"}],
    }


def make_prediction(**overrides):
    prediction = {"image_id": 1, "category_id": 1, "score": 0.95, "bbox": [10, 10, 30, 40]}
    prediction.update(overrides)
    return prediction


def test_perfect_detection_scores_one_for_all_iou_thresholds():
    report = evaluate_coco_detections(make_coco(), [make_prediction()])

    assert report["mAP50"] == 1.0
    assert report["mAP50_95"] == 1.0
    assert report["operating_point"]["precision"] == 1.0
    assert report["operating_point"]["recall"] == 1.0
    assert report["operating_point"]["f1"] == 1.0


def test_duplicate_detection_is_false_positive_at_operating_point():
    report = evaluate_coco_detections(
        make_coco(),
        [make_prediction(score=0.99), make_prediction(score=0.80)],
    )

    assert report["mAP50"] == 1.0
    assert report["operating_point"]["true_positives"] == 1
    assert report["operating_point"]["false_positives"] == 1
    assert report["operating_point"]["precision"] == 0.5


def test_wrong_class_prediction_is_false_positive_and_ground_truth_is_missed():
    coco = make_coco()
    coco["categories"].append({"id": 2, "name": "carton"})
    report = evaluate_coco_detections(
        coco,
        [make_prediction(category_id=2)],
    )

    assert report["per_class"]["1"]["operating_point"]["false_negatives"] == 1
    assert report["per_class"]["2"]["ground_truth_count"] == 0
    assert report["evaluated_class_count"] == 1


def test_missing_prediction_has_zero_ap_and_one_false_negative():
    report = evaluate_coco_detections(make_coco(), [])

    assert report["mAP50"] == 0.0
    assert report["mAP50_95"] == 0.0
    assert report["operating_point"]["false_negatives"] == 1
    assert report["operating_point"]["precision"] is None
    assert report["operating_point"]["recall"] == 0.0
    assert report["operating_point"]["f1"] == 0.0


def test_confidence_threshold_changes_operating_point_not_average_precision():
    predictions = [make_prediction(score=0.20)]
    low = evaluate_coco_detections(make_coco(), predictions, operating_threshold=0.10)
    high = evaluate_coco_detections(make_coco(), predictions, operating_threshold=0.50)

    assert low["mAP50"] == high["mAP50"] == 1.0
    assert low["operating_point"]["recall"] == 1.0
    assert high["operating_point"]["recall"] == 0.0


@pytest.mark.parametrize(
    "prediction, message",
    [
        (make_prediction(score=float("nan")), "finite"),
        (make_prediction(score=1.1), "between 0 and 1"),
        (make_prediction(bbox=[-1, 10, 30, 40]), "positive box"),
        (make_prediction(bbox=[90, 10, 30, 40]), "exceeds image dimensions"),
        (make_prediction(category_id=99), "unknown category"),
        (make_prediction(image_id=99), "unknown image"),
    ],
)
def test_invalid_predictions_are_rejected(prediction, message):
    with pytest.raises(ValueError, match=message):
        evaluate_coco_detections(make_coco(), [prediction])


def test_evaluator_rejects_crowd_annotations_until_supported():
    coco = make_coco()
    coco["annotations"][0]["iscrowd"] = 1

    with pytest.raises(ValueError, match="iscrowd"):
        evaluate_coco_detections(coco, [])


def test_evaluator_rejects_boolean_annotation_identifiers():
    coco = make_coco()
    coco["annotations"][0]["image_id"] = True

    with pytest.raises(ValueError, match="unknown image or category"):
        evaluate_coco_detections(coco, [])


def test_evaluator_rejects_invalid_operating_threshold():
    with pytest.raises(ValueError, match="operating_threshold"):
        evaluate_coco_detections(make_coco(), [], operating_threshold=float("nan"))


def write_approved_release_inputs(tmp_path, monkeypatch):
    import csv
    import hashlib
    import json

    tmp_path.mkdir(parents=True, exist_ok=True)
    image_bytes = b"approved-test-image"
    image_digest = hashlib.sha256(image_bytes).hexdigest()
    document = {
        "images": [{
            "id": 1,
            "file_name": "test/shelf.jpg",
            "width": 100,
            "height": 100,
            "sha256": image_digest,
        }],
        "annotations": [],
        "categories": [{"id": 1, "name": "product"}],
    }
    annotations = tmp_path / "instances_test.json"
    annotations.write_text(json.dumps(document), encoding="utf-8")

    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["split", "file_name", "size_bytes", "sha256"])
        writer.writeheader()
        writer.writerows([
            {"split": "train", "file_name": "train/shelf.jpg", "size_bytes": 10, "sha256": "1" * 64},
            {"split": "val", "file_name": "val/shelf.jpg", "size_bytes": 10, "sha256": "2" * 64},
            {"split": "test", "file_name": "test/shelf.jpg", "size_bytes": len(image_bytes), "sha256": image_digest},
        ])

    release_path = tmp_path / "approved-release.json"
    release = {
        "release_id": "release-123",
        "fingerprint": "a" * 64,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "approval": {
            "status": "APPROVED",
            "mode": "inference",
            "split_annotations_sha256": {
                "train": "3" * 64,
                "val": "4" * 64,
                "test": hashlib.sha256(annotations.read_bytes()).hexdigest(),
            },
        },
    }
    release_path.write_text(json.dumps(release), encoding="utf-8")
    monkeypatch.setenv("SMART_SHELF_DATASET_APPROVAL_STATUS", "APPROVED")
    monkeypatch.setenv("SMART_SHELF_DATASET_APPROVAL_MODE", "inference")
    monkeypatch.setenv("SMART_SHELF_DATASET_RELEASE_ID", "release-123")
    monkeypatch.setenv("SMART_SHELF_DATASET_RELEASE_FINGERPRINT", "a" * 64)
    monkeypatch.setenv("SMART_SHELF_DATASET_RELEASE_PATH", str(release_path))
    return annotations, manifest, document


def test_evaluation_runner_requires_inference_approval_and_binds_all_release_inputs(tmp_path, monkeypatch):
    from scripts.evaluate_vision_model import _approved_release_context

    annotations, manifest, document = write_approved_release_inputs(tmp_path, monkeypatch)

    assert _approved_release_context(annotations, manifest, document)["release_id"] == "release-123"

    monkeypatch.setenv("SMART_SHELF_DATASET_APPROVAL_MODE", "training")
    with pytest.raises(ValueError, match="approved for inference"):
        _approved_release_context(annotations, manifest, document)


def test_evaluation_runner_rejects_annotation_or_manifest_drift(tmp_path, monkeypatch):
    from scripts.evaluate_vision_model import _approved_release_context

    annotations, manifest, document = write_approved_release_inputs(tmp_path, monkeypatch)
    annotations.write_text('{"images":[],"annotations":[],"categories":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="annotations do not match"):
        _approved_release_context(annotations, manifest, document)

    annotations, manifest, document = write_approved_release_inputs(tmp_path / "second", monkeypatch)
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest does not match"):
        _approved_release_context(annotations, manifest, document)
