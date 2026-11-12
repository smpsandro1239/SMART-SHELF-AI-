"""Validation helpers for COCO-style object-detection datasets.

Run with:
    python -m app.coco_dataset --annotations /data/annotations/instances_train.json --image-root /data/images/train --check-files
"""
import argparse
import json
import math
from pathlib import Path
from typing import Any


def _is_integer(value: Any) -> bool:
    """Return true for JSON integers, explicitly excluding booleans."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_coco_document(document: Any, image_root: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["COCO document must be a JSON object"]

    images = document.get("images")
    annotations = document.get("annotations")
    categories = document.get("categories")
    if not all(isinstance(value, list) for value in (images, annotations, categories)):
        return ["COCO document must contain images, annotations and categories arrays"]

    image_by_id: dict[int, dict[str, Any]] = {}
    category_ids: set[int] = set()
    annotation_ids: set[int] = set()

    for index, item in enumerate(images):
        if not isinstance(item, dict):
            errors.append(f"images[{index}] must be an object")
            continue
        image_id = item.get("id")
        if not _is_integer(image_id) or image_id < 0:
            errors.append(f"images[{index}].id must be a non-negative integer")
            continue
        if image_id in image_by_id:
            errors.append(f"duplicate image id: {image_id}")
            continue
        image_by_id[image_id] = item

        for dimension in ("width", "height"):
            value = item.get(dimension)
            if not _is_integer(value) or value <= 0:
                errors.append(f"image {image_id} has invalid {dimension}")

        file_name = item.get("file_name")
        if not isinstance(file_name, str) or not file_name.strip() or "\\x00" in file_name:
            errors.append(f"image {image_id} has invalid file_name")
        elif image_root is not None:
            root = image_root.resolve()
            candidate = (root / file_name).resolve()
            if candidate != root and root not in candidate.parents:
                errors.append(f"image {image_id} file_name escapes image root")
            elif not candidate.is_file():
                errors.append(f"image {image_id} file is missing: {file_name}")

    for index, item in enumerate(categories):
        if not isinstance(item, dict):
            errors.append(f"categories[{index}] must be an object")
            continue
        category_id = item.get("id")
        if not _is_integer(category_id) or category_id < 0:
            errors.append(f"categories[{index}].id must be a non-negative integer")
            continue
        if category_id in category_ids:
            errors.append(f"duplicate category id: {category_id}")
        category_ids.add(category_id)
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            errors.append(f"category {category_id} has invalid name")

    for index, item in enumerate(annotations):
        if not isinstance(item, dict):
            errors.append(f"annotations[{index}] must be an object")
            continue
        annotation_id = item.get("id")
        if not _is_integer(annotation_id) or annotation_id < 0:
            errors.append(f"annotations[{index}].id must be a non-negative integer")
            annotation_label = f"at index {index}"
        else:
            annotation_label = str(annotation_id)
            if annotation_id in annotation_ids:
                errors.append(f"duplicate annotation id: {annotation_id}")
            else:
                annotation_ids.add(annotation_id)

        image_id = item.get("image_id")
        image = image_by_id.get(image_id) if _is_integer(image_id) else None
        if image is None:
            errors.append(f"annotation {annotation_label} references unknown image_id {image_id}")
            continue

        category_id = item.get("category_id")
        if not _is_integer(category_id) or category_id not in category_ids:
            errors.append(f"annotation {annotation_label} references unknown category_id {category_id}")

        bbox = item.get("bbox")
        if (
            not isinstance(bbox, list)
            or len(bbox) != 4
            or not all(_is_finite_number(value) for value in bbox)
        ):
            errors.append(f"annotation {annotation_label} bbox must contain four finite numbers [x, y, width, height]")
            continue

        x, y, width, height = bbox
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            errors.append(f"annotation {annotation_label} bbox has non-positive size or negative origin")
            continue

        image_width, image_height = image.get("width"), image.get("height")
        if _is_integer(image_width) and _is_integer(image_height):
            if x + width > image_width or y + height > image_height:
                errors.append(f"annotation {annotation_label} bbox exceeds image dimensions")

        area = item.get("area")
        if area is not None and (not _is_finite_number(area) or area <= 0):
            errors.append(f"annotation {annotation_label} has invalid area")

        iscrowd = item.get("iscrowd", 0)
        if not _is_integer(iscrowd) or iscrowd not in (0, 1):
            errors.append(f"annotation {annotation_label} iscrowd must be integer 0 or 1")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a COCO object-detection annotation file")
    parser.add_argument("--annotations", required=True, type=Path, help="Path to COCO JSON file")
    parser.add_argument("--image-root", type=Path, help="Optional root directory containing image files")
    parser.add_argument("--check-files", action="store_true", help="Verify image files exist under --image-root")
    args = parser.parse_args()
    if args.check_files and args.image_root is None:
        parser.error("--check-files requires --image-root")
    try:
        document = json.loads(args.annotations.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read COCO JSON: {exc}")
        return 2
    errors = validate_coco_document(document, args.image_root if args.check_files else None)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Dataset validation failed with {len(errors)} issue(s).")
        return 1
    print("COCO dataset validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
