from app.dataset_quality import analyze_dataset_quality


def document(prefix, *, empty=False, product_count=2, include_empty_space=True):
    images = [
        {"id": 1, "file_name": f"{prefix}/a.jpg", "width": 100, "height": 100},
        {"id": 2, "file_name": f"{prefix}/b.jpg", "width": 100, "height": 100},
    ]
    annotations = []
    for index in range(product_count):
        annotations.append({
            "id": index + 1, "image_id": 1, "category_id": 0,
            "bbox": [index * 10, 10, 5, 5], "area": 25, "iscrowd": 0,
        })
    if include_empty_space:
        annotations.append({
            "id": len(annotations) + 1, "image_id": 1, "category_id": 1,
            "bbox": [50, 50, 10, 10], "area": 100, "iscrowd": 0,
        })
    if empty:
        annotations = []
    return {
        "images": images,
        "annotations": annotations,
        "categories": [
            {"id": 0, "name": "product"},
            {"id": 1, "name": "empty_space"},
        ],
    }


def test_quality_report_counts_classes_and_unannotated_images():
    errors, report = analyze_dataset_quality({
        "train": document("train"),
        "val": document("val"),
        "test": document("test"),
    })
    assert errors == []
    assert report["splits"]["train"]["classes"]["0"]["instances"] == 2
    assert report["splits"]["train"]["classes"]["1"]["instances"] == 1
    assert report["splits"]["train"]["images_without_annotations"] == 1
    assert report["overall"]["images"] == 6
    assert report["overall"]["annotations"] == 9
    assert len(report["warnings"]) == 3


def test_negative_images_are_reported_as_warnings_not_errors():
    errors, report = analyze_dataset_quality({
        "train": document("train", empty=True),
        "val": document("val"),
        "test": document("test"),
    })
    assert errors == []
    assert report["splits"]["train"]["images_without_annotations"] == 2
    assert any("intentional negative examples" in warning for warning in report["warnings"])


def test_minimum_instances_threshold_is_opt_in():
    splits = {
        "train": document("train", product_count=1),
        "val": document("val", product_count=1),
        "test": document("test", product_count=1),
    }
    errors, _ = analyze_dataset_quality(splits)
    assert errors == []
    errors, report = analyze_dataset_quality(splits, min_instances_per_class=2)
    assert any("minimum is 2" in error for error in errors)
    assert report["splits"]["train"]["classes"]["0"]["below_minimum"] is True


def test_class_imbalance_threshold_is_configurable():
    splits = {
        "train": document("train", product_count=10),
        "val": document("val", product_count=10),
        "test": document("test", product_count=10),
    }
    errors, _ = analyze_dataset_quality(splits, max_class_imbalance_ratio=5)
    assert any("class imbalance ratio" in error for error in errors)


def test_missing_class_instances_are_reported():
    splits = {
        "train": document("train", include_empty_space=False),
        "val": document("val"),
        "test": document("test"),
    }
    errors, report = analyze_dataset_quality(splits)
    assert errors == []
    assert report["splits"]["train"]["classes"]["1"]["instances"] == 0
    assert report["splits"]["train"]["classes"]["1"]["share"] == 0.0


def test_invalid_thresholds_are_rejected():
    errors, _ = analyze_dataset_quality({"train": document("train")}, min_instances_per_class=-1)
    assert any("zero or greater" in error for error in errors)
    errors, _ = analyze_dataset_quality({"train": document("train")}, max_class_imbalance_ratio=0.5)
    assert any("greater than or equal to 1" in error for error in errors)


def test_invalid_coco_documents_are_reported():
    broken = document("train")
    broken["annotations"][0]["bbox"] = [0, 0, 0, 2]
    errors, _ = analyze_dataset_quality({"train": broken})
    assert any("bbox" in error for error in errors)
