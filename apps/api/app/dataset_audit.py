"""Audit COCO train/validation/test splits for leakage and class coverage.

Optional image metadata keys supported by this audit:
- capture_group_id / capture_group_key: stable capture group identifiers
- capture_session_id: database session identifier (namespaced as session:<id>)
- sequence_id: alternative grouping key
- sha256: content hash recorded by the dataset preparation pipeline

Example:
    python -m app.dataset_audit --train /data/annotations/instances_train.json \
        --val /data/annotations/instances_val.json \
        --test /data/annotations/instances_test.json
"""
import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.coco_dataset import validate_coco_document


def audit_splits(splits: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    report: dict[str, Any] = {"splits": {}, "cross_split": {}}
    canonical_categories: dict[int, str] | None = None
    seen_files: dict[str, str] = {}
    seen_hashes: dict[str, str] = {}
    seen_groups: dict[str, str] = {}

    for split_name, document in splits.items():
        validation_errors = validate_coco_document(document)
        errors.extend(f"{split_name}: {error}" for error in validation_errors)
        if not isinstance(document, dict):
            continue

        images = document.get("images", [])
        annotations = document.get("annotations", [])
        categories = document.get("categories", [])
        if not all(isinstance(value, list) for value in (images, annotations, categories)):
            continue

        current_categories: dict[int, str] = {}
        for item in categories:
            if isinstance(item, dict):
                category_id, name = item.get("id"), item.get("name")
                if isinstance(category_id, int) and not isinstance(category_id, bool) and isinstance(name, str):
                    current_categories[category_id] = name

        if canonical_categories is None:
            canonical_categories = current_categories
        elif current_categories != canonical_categories:
            errors.append(f"{split_name}: category IDs/names differ from the first supplied split")

        image_ids = {
            item.get("id") for item in images
            if isinstance(item, dict) and isinstance(item.get("id"), int) and not isinstance(item.get("id"), bool)
        }
        counts: Counter[int] = Counter()
        annotated_image_ids: set[int] = set()
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            category_id = annotation.get("category_id")
            if isinstance(category_id, int) and not isinstance(category_id, bool):
                counts[category_id] += 1
            image_id = annotation.get("image_id")
            if isinstance(image_id, int) and not isinstance(image_id, bool):
                annotated_image_ids.add(image_id)

        report["splits"][split_name] = {
            "images": len(images),
            "annotations": len(annotations),
            "images_without_annotations": len(image_ids - annotated_image_ids),
            "classes": {
                str(category_id): {
                    "name": current_categories.get(category_id, "unknown"),
                    "instances": counts.get(category_id, 0),
                }
                for category_id in sorted(current_categories)
            },
        }

        local_files: set[str] = set()
        local_hashes: set[str] = set()
        for image in images:
            if not isinstance(image, dict):
                continue

            file_name = image.get("file_name")
            if isinstance(file_name, str) and file_name:
                if file_name in local_files:
                    errors.append(f"{split_name}: duplicate file_name within split: {file_name}")
                local_files.add(file_name)
                if file_name in seen_files and seen_files[file_name] != split_name:
                    errors.append(
                        f"image file_name appears in both {seen_files[file_name]} and {split_name}: {file_name}"
                    )
                else:
                    seen_files[file_name] = split_name

            content_hash = image.get("sha256")
            if isinstance(content_hash, str) and content_hash:
                if content_hash in local_hashes:
                    errors.append(f"{split_name}: duplicate sha256 within split: {content_hash}")
                local_hashes.add(content_hash)
                if content_hash in seen_hashes and seen_hashes[content_hash] != split_name:
                    errors.append(
                        f"image sha256 appears in both {seen_hashes[content_hash]} and {split_name}"
                    )
                else:
                    seen_hashes[content_hash] = split_name

            # Accept metadata emitted by the reviewed-candidate API as well as
            # COCO's canonical capture_group_id. Prefix database IDs to avoid
            # collisions with arbitrary sequence/group labels.
            group_id = image.get("capture_group_id")
            if group_id is None:
                group_id = image.get("capture_group_key")
            if group_id is None and image.get("capture_session_id") is not None:
                session_id = image.get("capture_session_id")
                if isinstance(session_id, (str, int)) and not isinstance(session_id, bool):
                    group_id = f"session:{str(session_id).strip()}"
            if group_id is None:
                group_id = image.get("sequence_id")
            if isinstance(group_id, (str, int)) and not isinstance(group_id, bool):
                group_key = str(group_id).strip()
                if group_key:
                    previous_split = seen_groups.get(group_key)
                    if previous_split is not None and previous_split != split_name:
                        errors.append(
                            f"capture group {group_key} is split between {previous_split} and {split_name}"
                        )
                    else:
                        seen_groups[group_key] = split_name

    report["cross_split"] = {
        "unique_file_names": len(seen_files),
        "unique_sha256_values": len(seen_hashes),
        "unique_capture_groups": len(seen_groups),
    }
    return errors, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit COCO dataset splits for leakage and class consistency")
    parser.add_argument("--train", required=True, type=Path, help="COCO training annotations")
    parser.add_argument("--val", required=True, type=Path, help="COCO validation annotations")
    parser.add_argument("--test", required=True, type=Path, help="COCO test annotations")
    parser.add_argument("--json-report", type=Path, help="Optional path to write the audit report as JSON")
    args = parser.parse_args()

    documents: dict[str, Any] = {}
    for split_name in ("train", "val", "test"):
        path = getattr(args, split_name)
        try:
            documents[split_name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: cannot read {split_name} annotations: {exc}")
            return 2

    errors, report = audit_splits(documents)
    report["errors"] = errors
    report["status"] = "failed" if errors else "passed"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_report:
        try:
            args.json_report.parent.mkdir(parents=True, exist_ok=True)
            args.json_report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"ERROR: cannot write JSON report: {exc}")
            return 2
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Dataset split audit failed with {len(errors)} issue(s).")
        return 1
    print("Dataset split audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
