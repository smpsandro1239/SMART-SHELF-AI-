import math

from app.coco_dataset import validate_coco_document


def valid_document():
    return {
        "images": [{"id": 1, "file_name": "image.jpg", "width": 100, "height": 80}],
        "annotations": [{
            "id": 1, "image_id": 1, "category_id": 0,
            "bbox": [10, 12, 20, 30], "area": 600, "iscrowd": 0,
        }],
        "categories": [{"id": 0, "name": "product"}],
    }


def test_coco_validator_accepts_valid_document():
    assert validate_coco_document(valid_document()) == []


def test_coco_validator_rejects_non_object_document():
    assert validate_coco_document([]) == ["COCO document must be a JSON object"]


def test_coco_validator_rejects_bbox_outside_image():
    document = valid_document()
    document["annotations"][0]["bbox"] = [90, 10, 20, 20]
    assert any("exceeds image dimensions" in error for error in validate_coco_document(document))


def test_coco_validator_rejects_unknown_image_and_category():
    document = valid_document()
    document["annotations"][0]["image_id"] = 99
    document["annotations"][0]["category_id"] = 88
    errors = validate_coco_document(document)
    assert any("unknown image_id" in error for error in errors)


def test_coco_validator_rejects_duplicate_ids_and_invalid_boxes():
    document = valid_document()
    document["images"].append(dict(document["images"][0]))
    document["annotations"][0]["bbox"] = [10, 10, -2, 5]
    errors = validate_coco_document(document)
    assert any("duplicate image id" in error for error in errors)
    assert any("non-positive size" in error for error in errors)


def test_coco_validator_rejects_boolean_integer_fields():
    document = valid_document()
    document["images"][0]["width"] = True
    document["annotations"][0]["iscrowd"] = True
    errors = validate_coco_document(document)
    assert any("invalid width" in error for error in errors)
    assert any("iscrowd must be integer" in error for error in errors)


def test_coco_validator_rejects_non_finite_bbox_values():
    document = valid_document()
    document["annotations"][0]["bbox"] = [10, 10, math.inf, 5]
    errors = validate_coco_document(document)
    assert any("four finite numbers" in error for error in errors)


def test_coco_validator_prevents_image_path_traversal(tmp_path):
    document = valid_document()
    document["images"][0]["file_name"] = "../../outside.jpg"
    errors = validate_coco_document(document, tmp_path)
    assert any("escapes image root" in error for error in errors)
