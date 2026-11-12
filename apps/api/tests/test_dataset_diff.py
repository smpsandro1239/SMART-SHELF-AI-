from app.dataset_diff import compare_dataset_versions


def manifest(name, digest, split="train", size="100"):
    return {"split": split, "file_name": name, "sha256": digest, "size_bytes": size}


def coco(file_name="a.jpg", bbox=None, image_id=1):
    annotation = []
    if bbox is not None:
        annotation = [{
            "id": 10, "image_id": image_id, "category_id": 0,
            "bbox": bbox, "area": bbox[2] * bbox[3], "iscrowd": 0,
        }]
    return {
        "images": [{"id": image_id, "file_name": file_name, "width": 100, "height": 100}],
        "annotations": annotation,
        "categories": [{"id": 0, "name": "product"}],
    }


def release(train):
    return {"train": train, "val": coco("val.jpg", image_id=2), "test": coco("test.jpg", image_id=3)}


def rows(train_hash, train_name="a.jpg"):
    return [
        manifest(train_name, train_hash),
        manifest("val.jpg", "b" * 64, "val"),
        manifest("test.jpg", "c" * 64, "test"),
    ]


def test_identical_releases_have_no_image_or_annotation_changes():
    report, errors = compare_dataset_versions(rows("a" * 64), rows("a" * 64), release(coco()), release(coco()))

    assert errors == []
    assert report["images"]["summary"]["unchanged"] == 3
    assert report["annotations"]["summary"]["annotations_changed"] == 0


def test_added_removed_and_modified_images_are_reported():
    old_rows = rows("a" * 64)
    new_rows = [
        manifest("a.jpg", "d" * 64),
        manifest("new.jpg", "e" * 64),
        manifest("val.jpg", "b" * 64, "val"),
        manifest("test.jpg", "c" * 64, "test"),
    ]
    old_docs = release(coco())
    new_docs = release(coco())
    new_docs["train"]["images"].append({"id": 4, "file_name": "new.jpg", "width": 100, "height": 100})

    report, errors = compare_dataset_versions(old_rows, new_rows, old_docs, new_docs)

    assert errors == []
    assert report["images"]["summary"]["modified"] == 1
    assert report["images"]["summary"]["added"] == 1


def test_rename_and_split_move_are_detected_by_unique_hash():
    old_rows = rows("a" * 64)
    new_rows = [
        manifest("renamed.jpg", "a" * 64),
        manifest("val.jpg", "b" * 64, "val"),
        manifest("test.jpg", "c" * 64, "test"),
    ]
    old_docs = release(coco())
    new_docs = release(coco("renamed.jpg"))

    report, errors = compare_dataset_versions(old_rows, new_rows, old_docs, new_docs)

    assert errors == []
    assert report["images"]["summary"]["renamed"] == 1
    assert report["images"]["summary"]["added"] == 0
    assert report["images"]["summary"]["removed"] == 0


def test_annotation_bbox_change_is_reported_as_changed():
    old_docs = release(coco(bbox=[1, 2, 10, 10]))
    new_docs = release(coco(bbox=[2, 2, 10, 10]))

    report, errors = compare_dataset_versions(rows("a" * 64), rows("a" * 64), old_docs, new_docs)

    assert errors == []
    assert report["annotations"]["summary"]["annotations_changed"] == 1
    assert report["annotations"]["summary"]["annotations_added"] == 0
    assert report["annotations"]["summary"]["annotations_removed"] == 0


def test_split_move_is_reported_separately():
    old_rows = rows("a" * 64)
    new_rows = [
        manifest("a.jpg", "a" * 64, "val"),
        manifest("val.jpg", "b" * 64, "val"),
        manifest("test.jpg", "c" * 64, "test"),
    ]
    old_docs = release(coco())
    new_docs = {
        "train": {"images": [], "annotations": [], "categories": [{"id": 0, "name": "product"}]},
        "val": {
            "images": [
                {"id": 4, "file_name": "a.jpg", "width": 100, "height": 100},
                {"id": 2, "file_name": "val.jpg", "width": 100, "height": 100},
            ],
            "annotations": [], "categories": [{"id": 0, "name": "product"}],
        },
        "test": coco("test.jpg", image_id=3),
    }

    report, errors = compare_dataset_versions(old_rows, new_rows, old_docs, new_docs)

    assert errors == []
    assert report["images"]["summary"]["moved_between_splits"] == 1


def test_invalid_documents_block_comparison():
    bad = {
        "images": [{"id": 1, "file_name": "bad.jpg", "width": 0, "height": 100}],
        "annotations": [],
        "categories": [{"id": 0, "name": "product"}],
    }

    report, errors = compare_dataset_versions(rows("a" * 64), rows("a" * 64), release(bad), release(coco()))

    assert report is None
    assert errors


def test_duplicate_manifest_entries_are_rejected():
    duplicated = rows("a" * 64)
    duplicated.append(manifest("a.jpg", "f" * 64))

    report, errors = compare_dataset_versions(duplicated, rows("a" * 64), release(coco()), release(coco()))

    assert report is None
    assert any("duplicate manifest" in error for error in errors)
