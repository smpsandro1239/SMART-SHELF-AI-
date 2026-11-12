"""Dataset quality report for COCO object-detection splits.

This tool reports class balance and annotation coverage. Quality thresholds are
opt-in: the project does not impose arbitrary minimum dataset sizes.
"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

from app.coco_dataset import validate_coco_document


def analyze_dataset_quality(
    splits: dict[str, Any],
    *,
    min_instances_per_class: int = 0,
    max_class_imbalance_ratio: float | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Return threshold/structure errors and descriptive quality statistics."""
    errors: list[str] = []
    report: dict[str, Any] = {
        "thresholds": {
            "min_instances_per_class": min_instances_per_class,
            "max_class_imbalance_ratio": max_class_imbalance_ratio,
        },
        "splits": {},
        "overall": {},
        "warnings": [],
    }
    if min_instances_per_class < 0:
        errors.append("min_instances_per_class must be zero or greater")
    if max_class_imbalance_ratio is not None and (
        isinstance(max_class_imbalance_ratio, bool)
        or not isinstance(max_class_imbalance_ratio, (int, float))
        or not math.isfinite(max_class_imbalance_ratio)
        or max_class_imbalance_ratio < 1
    ):
        errors.append("max_class_imbalance_ratio must be a finite number greater than or equal to 1")
    if errors:
        return errors, report

    overall_counts: Counter[int] = Counter()
    overall_images = 0
    overall_annotations = 0
    overall_unannotated = 0
    canonical_categories: dict[int, str] | None = None

    for split_name, document in splits.items():
        validation = validate_coco_document(document)
        errors.extend(f"{split_name}: {message}" for message in validation)
        if not isinstance(document, dict):
            continue
        images = document.get("images")
        annotations = document.get("annotations")
        categories = document.get("categories")
        if not all(isinstance(value, list) for value in (images, annotations, categories)):
            continue

        category_map = {
            item["id"]: item["name"]
            for item in categories
            if isinstance(item, dict)
            and isinstance(item.get("id"), int)
            and not isinstance(item.get("id"), bool)
            and isinstance(item.get("name"), str)
        }
        if canonical_categories is None:
            canonical_categories = category_map
        elif category_map != canonical_categories:
            errors.append(f"{split_name}: category IDs/names differ from the first supplied split")

        counts: Counter[int] = Counter()
        per_image: Counter[int] = Counter()
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            category_id = annotation.get("category_id")
            image_id = annotation.get("image_id")
            if isinstance(category_id, int) and not isinstance(category_id, bool):
                counts[category_id] += 1
            if isinstance(image_id, int) and not isinstance(image_id, bool):
                per_image[image_id] += 1

        image_ids = {
            image["id"] for image in images
            if isinstance(image, dict)
            and isinstance(image.get("id"), int)
            and not isinstance(image.get("id"), bool)
        }
        unannotated = len(image_ids - set(per_image))
        instance_counts = [per_image.get(image_id, 0) for image_id in image_ids]
        class_report = {}
        for category_id, name in sorted(category_map.items()):
            amount = counts.get(category_id, 0)
            class_report[str(category_id)] = {
                "name": name,
                "instances": amount,
                "share": round(amount / len(annotations), 6) if annotations else 0.0,
                "below_minimum": amount < min_instances_per_class if min_instances_per_class else False,
            }
            if min_instances_per_class and amount < min_instances_per_class:
                errors.append(
                    f"{split_name}: class {name!r} has {amount} instances; "
                    f"minimum is {min_instances_per_class}"
                )

        nonzero = [value for value in counts.values() if value > 0]
        imbalance = (max(nonzero) / min(nonzero)) if nonzero else None
        if (
            max_class_imbalance_ratio is not None
            and imbalance is not None
            and imbalance > max_class_imbalance_ratio
        ):
            errors.append(
                f"{split_name}: class imbalance ratio {imbalance:.3f} exceeds "
                f"maximum {max_class_imbalance_ratio:.3f}"
            )

        split_report = {
            "images": len(images),
            "annotations": len(annotations),
            "images_without_annotations": unannotated,
            "images_without_annotations_share": round(unannotated / len(images), 6) if images else 0.0,
            "instances_per_annotated_image": {
                "min": min((value for value in instance_counts if value > 0), default=0),
                "median": median([value for value in instance_counts if value > 0]) if any(instance_counts) else 0,
                "max": max(instance_counts, default=0),
                "mean": round(sum(instance_counts) / len(image_ids), 3) if image_ids else 0.0,
            },
            "class_imbalance_ratio": round(imbalance, 3) if imbalance is not None else None,
            "classes": class_report,
        }
        report["splits"][split_name] = split_report
        overall_counts.update(counts)
        overall_images += len(images)
        overall_annotations += len(annotations)
        overall_unannotated += unannotated

        if unannotated:
            report["warnings"].append(
                f"{split_name}: {unannotated} image(s) without annotations; "
                "review whether these are intentional negative examples"
            )
        if not annotations:
            report["warnings"].append(f"{split_name}: split contains no annotations")

    overall_categories = canonical_categories or {}
    report["overall"] = {
        "images": overall_images,
        "annotations": overall_annotations,
        "images_without_annotations": overall_unannotated,
        "classes": {
            str(category_id): {
                "name": name,
                "instances": overall_counts.get(category_id, 0),
                "share": round(overall_counts.get(category_id, 0) / overall_annotations, 6)
                if overall_annotations else 0.0,
            }
            for category_id, name in sorted(overall_categories.items())
        },
    }
    return errors, report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report COCO dataset class balance and annotation coverage"
    )
    parser.add_argument("--train", required=True, type=Path, help="COCO training annotations")
    parser.add_argument("--val", required=True, type=Path, help="COCO validation annotations")
    parser.add_argument("--test", required=True, type=Path, help="COCO test annotations")
    parser.add_argument("--json-report", type=Path, help="Optional JSON report output path")
    parser.add_argument(
        "--min-instances-per-class",
        type=int,
        default=0,
        help="Optional minimum instances per class per split; default 0 only reports",
    )
    parser.add_argument(
        "--max-class-imbalance-ratio",
        type=float,
        help="Optional maximum max/min non-zero class instance ratio per split (>= 1)",
    )
    args = parser.parse_args()

    documents: dict[str, Any] = {}
    for split_name in ("train", "val", "test"):
        path = getattr(args, split_name)
        try:
            documents[split_name] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: cannot read {split_name} annotations: {exc}")
            return 2

    errors, report = analyze_dataset_quality(
        documents,
        min_instances_per_class=args.min_instances_per_class,
        max_class_imbalance_ratio=args.max_class_imbalance_ratio,
    )
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
        for message in errors:
            print(f"ERROR: {message}")
        print(f"Dataset quality check failed with {len(errors)} issue(s).")
        return 1
    print("Dataset quality report generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
