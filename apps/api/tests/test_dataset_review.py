import copy
import hashlib
import json

from app.dataset_review import (
    create_review_template,
    validate_visual_review_record,
)


def coco():
    return {
        "images": [
            {"id": 1, "file_name": "one.jpg", "width": 100, "height": 80},
            {"id": 2, "file_name": "two.jpg", "width": 50, "height": 40},
        ],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 0, "bbox": [1, 2, 10, 12]},
        ],
        "categories": [{"id": 0, "name": "product"}],
    }


def approved_record(document):
    digest = hashlib.sha256(b"coco-v1").hexdigest()
    record, errors = create_review_template(document, "train", digest)
    assert errors == []
    for item in record["reviews"]:
        item.update({
            "decision": "APPROVED",
            "reviewer": "reviewer-01",
            "reviewed_at": "2026-11-12T10:00:00Z",
            "notes": "Visual check completed",
        })
    return record, digest


def test_template_contains_every_image_and_annotation_fingerprint():
    template, errors = create_review_template(coco(), "train", "a" * 64)

    assert errors == []
    assert [item["image_id"] for item in template["reviews"]] == [1, 2]
    assert all(item["decision"] == "PENDING" for item in template["reviews"])
    assert len(template["reviews"][0]["annotations_sha256"]) == 64


def test_complete_current_human_review_passes():
    document = coco()
    record, digest = approved_record(document)

    errors, report = validate_visual_review_record(record, document, "train", digest)

    assert errors == []
    assert report["status"] == "APPROVED"
    assert report["approved_images"] == 2


def test_missing_review_blocks_dataset():
    document = coco()
    record, digest = approved_record(document)
    record["reviews"].pop()

    errors, report = validate_visual_review_record(record, document, "train", digest)

    assert any("missing human review" in error for error in errors)
    assert report["status"] == "BLOCKED"


def test_non_approved_decision_blocks_dataset():
    document = coco()
    record, digest = approved_record(document)
    record["reviews"][0]["decision"] = "NEEDS_CORRECTION"

    errors, _ = validate_visual_review_record(record, document, "train", digest)

    assert any("is not approved" in error for error in errors)


def test_changed_annotations_invalidate_previous_review():
    document = coco()
    record, digest = approved_record(document)
    changed = copy.deepcopy(document)
    changed["annotations"][0]["bbox"] = [2, 2, 10, 12]

    errors, _ = validate_visual_review_record(record, changed, "train", digest)

    assert any("annotations changed since review" in error for error in errors)


def test_changed_coco_file_hash_blocks_review():
    document = coco()
    record, digest = approved_record(document)

    errors, _ = validate_visual_review_record(
        record, document, "train", hashlib.sha256(b"coco-v2").hexdigest()
    )

    assert any("different COCO file hash" in error for error in errors)


def test_duplicate_and_unknown_image_ids_are_rejected():
    document = coco()
    record, digest = approved_record(document)
    record["reviews"].append(copy.deepcopy(record["reviews"][0]))
    record["reviews"][-1]["image_id"] = 999

    errors, _ = validate_visual_review_record(record, document, "train", digest)

    assert any("duplicate image_id" in error for error in errors)
    assert any("absent from COCO" in error for error in errors)


def test_invalid_reviewer_and_timestamp_are_rejected():
    document = coco()
    record, digest = approved_record(document)
    record["reviews"][0]["reviewer"] = " "
    record["reviews"][0]["reviewed_at"] = "yesterday"

    errors, _ = validate_visual_review_record(record, document, "train", digest)

    assert any(".reviewer is required" in error for error in errors)
    assert any(".reviewed_at must be an ISO 8601" in error for error in errors)


def test_template_rejects_invalid_split_and_hash():
    template, errors = create_review_template(coco(), "production", "bad")

    assert template is None
    assert len(errors) == 2


def test_unhashable_decision_is_rejected_without_crashing():
    document = coco()
    record, digest = approved_record(document)
    record["reviews"][0]["decision"] = ["APPROVED"]

    errors, report = validate_visual_review_record(record, document, "train", digest)

    assert report["status"] == "BLOCKED"
    assert any(".decision must be APPROVED" in error for error in errors)
