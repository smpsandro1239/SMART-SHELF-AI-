from app.dataset_audit import audit_splits


def coco_document(file_name, capture_group, category_name="product", sha256=None):
    image = {
        "id": 1,
        "file_name": file_name,
        "width": 100,
        "height": 80,
        "capture_group_id": capture_group,
    }
    if sha256:
        image["sha256"] = sha256
    return {
        "images": [image],
        "annotations": [{
            "id": 1,
            "image_id": 1,
            "category_id": 0,
            "bbox": [10, 10, 20, 20],
            "area": 400,
            "iscrowd": 0,
        }],
        "categories": [{"id": 0, "name": category_name}],
    }


def test_dataset_audit_accepts_disjoint_splits_and_reports_counts():
    errors, report = audit_splits({
        "train": coco_document("train/a.jpg", "session-a"),
        "val": coco_document("val/b.jpg", "session-b"),
        "test": coco_document("test/c.jpg", "session-c"),
    })
    assert errors == []
    assert report["splits"]["train"]["images"] == 1
    assert report["splits"]["val"]["classes"]["0"]["instances"] == 1
    assert report["cross_split"]["unique_capture_groups"] == 3


def test_dataset_audit_allows_multiple_images_from_same_group_in_one_split():
    train = coco_document("train/a.jpg", "session-a")
    second = coco_document("train/b.jpg", "session-a")
    second["images"][0]["id"] = 2
    second["annotations"][0]["image_id"] = 2
    second["annotations"][0]["id"] = 2
    train["images"].extend(second["images"])
    train["annotations"].extend(second["annotations"])
    errors, _ = audit_splits({
        "train": train,
        "val": coco_document("val/b.jpg", "session-b"),
        "test": coco_document("test/c.jpg", "session-c"),
    })
    assert errors == []


def test_dataset_audit_detects_duplicate_file_names():
    errors, _ = audit_splits({
        "train": coco_document("same.jpg", "session-a"),
        "val": coco_document("same.jpg", "session-b"),
        "test": coco_document("test.jpg", "session-c"),
    })
    assert any("file_name appears in both" in error for error in errors)


def test_dataset_audit_detects_capture_group_leakage_between_splits():
    errors, _ = audit_splits({
        "train": coco_document("train/a.jpg", "same-session"),
        "val": coco_document("val/b.jpg", "same-session"),
        "test": coco_document("test/c.jpg", "other-session"),
    })
    assert any("capture group same-session is split" in error for error in errors)


def test_dataset_audit_detects_duplicate_content_hash():
    errors, _ = audit_splits({
        "train": coco_document("train/a.jpg", "session-a", sha256="abc"),
        "val": coco_document("val/b.jpg", "session-b", sha256="abc"),
        "test": coco_document("test/c.jpg", "session-c", sha256="def"),
    })
    assert any("sha256 appears in both" in error for error in errors)


def test_dataset_audit_requires_identical_class_mapping():
    errors, _ = audit_splits({
        "train": coco_document("train/a.jpg", "session-a", category_name="product"),
        "val": coco_document("val/b.jpg", "session-b", category_name="item"),
        "test": coco_document("test/c.jpg", "session-c", category_name="product"),
    })
    assert any("category IDs/names differ" in error for error in errors)


def test_dataset_audit_reports_invalid_annotations():
    broken = coco_document("train/a.jpg", "session-a")
    broken["annotations"][0]["bbox"] = [1, 2, 0, 4]
    errors, _ = audit_splits({
        "train": broken,
        "val": coco_document("val/b.jpg", "session-b"),
        "test": coco_document("test/c.jpg", "session-c"),
    })
    assert any("train: annotation 1 bbox" in error for error in errors)


def test_dataset_audit_detects_capture_group_key_leakage():
    train = coco_document("train/a.jpg", None)
    val = coco_document("val/b.jpg", None)
    train["images"][0]["capture_group_key"] = "session:42"
    val["images"][0]["capture_group_key"] = "session:42"
    errors, report = audit_splits({
        "train": train,
        "val": val,
        "test": coco_document("test/c.jpg", "session-c"),
    })
    assert any("capture group session:42 is split" in error for error in errors)
    assert report["cross_split"]["unique_capture_groups"] == 2


def test_dataset_audit_normalizes_capture_session_id_namespace():
    train = coco_document("train/a.jpg", None)
    val = coco_document("val/b.jpg", None)
    train["images"][0]["capture_session_id"] = 17
    val["images"][0]["capture_session_id"] = "17"
    errors, _ = audit_splits({
        "train": train,
        "val": val,
        "test": coco_document("test/c.jpg", "session-c"),
    })
    assert any("capture group session:17 is split" in error for error in errors)


def test_dataset_audit_prefers_explicit_capture_group_over_sequence_id():
    train = coco_document("train/a.jpg", "session-a")
    val = coco_document("val/b.jpg", "session-b")
    train["images"][0]["sequence_id"] = "shared-sequence"
    val["images"][0]["sequence_id"] = "shared-sequence"
    train["images"][0]["capture_group_key"] = "capture-a"
    val["images"][0]["capture_group_key"] = "capture-b"
    errors, _ = audit_splits({
        "train": train,
        "val": val,
        "test": coco_document("test/c.jpg", "session-c"),
    })
    assert not any("shared-sequence" in error for error in errors)
