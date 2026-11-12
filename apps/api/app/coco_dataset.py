"""Validation helpers for COCO-style object-detection datasets.

Run with:
    python -m app.coco_dataset --annotations /data/annotations/instances_train.json --image-root /data/images/train --check-files
"""
import argparse
import json
from pathlib import Path
from typing import Any


def validate_coco_document(document: dict[str, Any], image_root: Path | None = None) -> list[str]:
    errors: list[str] = []
    images = document.get("images")
    annotations = document.get("annotations")
    categories = document.get("categories")
    if not isinstance(images, list) or not isinstance(annotations, list) or not isinstance(categories, list):
        return ["COCO document must contain images, annotations and categories arrays"]

    image_by_id: dict[int, dict[str, Any]] = {}
    category_ids: set[int] = set()
    annotation_ids: set[int] = set()

    for index, item in enumerate(images):
        if not isinstance(item, dict):
            errors.append(f"images[{index}] must be an object")
            continue
        image_id = item.get("id")
        if not isinstance(image_id, int) or isinstance(image_id, bool):
            errors.append(f"images[{index}].id must be an integer")
            continue
        if image_id in image_by_id:
            errors.append(f"duplicate image id: {image_id}")
        image_by_id[image_id] = item
        if not isinstance(item.get("width"), int) or item["width"] <= 0:
            errors.append(f"image {image_id} has invalid width")
        if not isinstance(item.get("height"), int) or item["height"] <= 0:
            errors.append(f"image {image_id} has invalid height")
        file_name = item.get("file_name")
        if not isinstance(file_name, str) or not file_name.strip():
            errors.append(f"image {image_id} has invalid file_name")
        elif image_root is not None:
            candidate = (image_root / file_name).resolve()
            root = image_root.resolve()
            if candidate != root and root not in candidate.parents:
                errors.append(f"image {image_id} file_name escapes image root")
            elif not candidate.is_file():
                errors.append(f"image {image_id} file is missing: {file_name}")

    for index, item in enumerate(categories):
        if not isinstance(item, dict):
            errors.append(f"categories[{index}] must be an object")
            continue
        category_id = item.get("id")
        if not isinstance(category_id, int) or isinstance(category_id, bool):
            errors.append(f"categories[{index}].id must be an integer")
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
        if not isinstance(annotation_id, int) or isinstance(annotation_id, bool):
            errors.append(f"annotations[{index}].id must be an integer")
        elif annotation_id in annotation_ids:
            errors.append(f"duplicate annotation id: {annotation_id}")
        else:
            annotation_ids.add(annotation_id)

        image_id = item.get("image_id")
        image = image_by_id.get(image_id) if isinstance(image_id, int) else None
        if image is None:
            errors.append(f"annotation {annotation_id} references unknown image_id {image_id}")
            continue
        category_id = item.get("category_id")
        if category_id not in category_ids:
            errors.append(f"annotation {annotation_id} references unknown category_id {category_id}")
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4 or any(
            not isinstance(value, (int, float)) or isinstance(value, bool) for value in (bbox or [])
        ):
            errors.append(f"annotation {annotation_id} bbox must be [x, y, width, height]")
            continue
        x, y, width, height = bbox
        if width <= 0 or height <= 0 or x < 0 or y < 0:
            errors.append(f"annotation {annotation_id} bbox has non-positive size or negative origin")
            continue
        image_width, image_height = image.get("width"), image.get("height")
        if isinstance(image_width, int) and isinstance(image_height, int):
            if x + width > image_width or y + height > image_height:
                errors.append(f"annotation {annotation_id} bbox exceeds image dimensions")
        area = item.get("area")
        if area is not None and (
            not isinstance(area, (int, float)) or isinstance(area, bool) or area <= 0
        ):
            errors.append(f"annotation {annotation_id} has invalid area")
        iscrowd = item.get("iscrowd", 0)
        if iscrowd not in (0, 1):
            errors.append(f"annotation {annotation_id} iscrowd must be 0 or 1")

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
