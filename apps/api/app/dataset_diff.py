"""Compare two dataset releases using manifests and COCO annotations.

The report contains metadata and aggregate deltas only; it never copies image data.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.coco_dataset import validate_coco_document
from app.dataset_integrity import SPLITS, read_manifest


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row["split"], row["file_name"])
        if key in indexed:
            raise ValueError(f"duplicate manifest entry: {key[0]}/{key[1]}")
        indexed[key] = row
    return indexed


def _category_names(document: dict[str, Any]) -> dict[int, str]:
    return {item["id"]: item["name"] for item in document["categories"]}


def _annotation_counter(
    document: dict[str, Any], image_id: int, categories: dict[int, str]
) -> Counter[str]:
    values: Counter[str] = Counter()
    for annotation in document["annotations"]:
        if annotation["image_id"] != image_id:
            continue
        semantic = {
            "category": categories[annotation["category_id"]],
            "bbox": annotation["bbox"],
            "area": annotation.get("area"),
            "iscrowd": annotation.get("iscrowd", 0),
        }
        key = json.dumps(semantic, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        values[key] += 1
    return values


def _compare_annotations(
    old_documents: dict[str, Any], new_documents: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    per_split: dict[str, Any] = {}
    totals = {"images_compared": 0, "images_added": 0, "images_removed": 0,
              "images_with_annotation_changes": 0, "annotations_added": 0,
              "annotations_removed": 0, "annotations_changed": 0}

    for split in SPLITS:
        old_doc, new_doc = old_documents[split], new_documents[split]
        errors.extend(f"old {split}: {item}" for item in validate_coco_document(old_doc))
        errors.extend(f"new {split}: {item}" for item in validate_coco_document(new_doc))
        if errors:
            continue

        old_images = {item["file_name"]: item for item in old_doc["images"]}
        new_images = {item["file_name"]: item for item in new_doc["images"]}
        old_categories = _category_names(old_doc)
        new_categories = _category_names(new_doc)
        common_names = sorted(set(old_images) & set(new_images))
        added_names = sorted(set(new_images) - set(old_images))
        removed_names = sorted(set(old_images) - set(new_images))
        changed_images = []
        split_totals = {"images_compared": len(common_names), "images_added": len(added_names),
                        "images_removed": len(removed_names), "images_with_annotation_changes": 0,
                        "annotations_added": 0, "annotations_removed": 0, "annotations_changed": 0}

        for name in common_names:
            old_counter = _annotation_counter(old_doc, old_images[name]["id"], old_categories)
            new_counter = _annotation_counter(new_doc, new_images[name]["id"], new_categories)
            removed = old_counter - new_counter
            added = new_counter - old_counter
            removed_count, added_count = sum(removed.values()), sum(added.values())
            changed = min(removed_count, added_count)
            net_removed, net_added = removed_count - changed, added_count - changed
            if removed_count or added_count:
                split_totals["images_with_annotation_changes"] += 1
                changed_images.append({
                    "file_name": name,
                    "annotations_changed": changed,
                    "annotations_added": net_added,
                    "annotations_removed": net_removed,
                })
                split_totals["annotations_changed"] += changed
                split_totals["annotations_added"] += net_added
                split_totals["annotations_removed"] += net_removed

        per_split[split] = {
            **split_totals,
            "added_images": added_names,
            "removed_images": removed_names,
            "changed_images": changed_images,
        }
        for key in totals:
            totals[key] += split_totals[key]

    return {"summary": totals, "splits": per_split}, errors


def compare_dataset_versions(
    old_manifest_rows: list[dict[str, str]],
    new_manifest_rows: list[dict[str, str]],
    old_documents: dict[str, Any],
    new_documents: dict[str, Any],
    old_manifest_sha256: str | None = None,
    new_manifest_sha256: str | None = None,
    old_coco_sha256: dict[str, str] | None = None,
    new_coco_sha256: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Return a deterministic metadata diff between two dataset releases."""
    errors: list[str] = []
    if set(old_documents) != set(SPLITS) or set(new_documents) != set(SPLITS):
        return None, ["both releases must provide train, val and test COCO documents"]

    try:
        old_index = _manifest_index(old_manifest_rows)
        new_index = _manifest_index(new_manifest_rows)
    except (KeyError, TypeError, ValueError) as exc:
        return None, [f"invalid manifest rows: {exc}"]

    for label, rows in (("old", old_manifest_rows), ("new", new_manifest_rows)):
        for row in rows:
            if row.get("split") not in SPLITS or not row.get("file_name"):
                errors.append(f"{label} manifest contains invalid split or file_name")
            if not row.get("sha256") or not row.get("size_bytes"):
                errors.append(f"{label} manifest contains missing hash or size")
    if errors:
        return None, errors

    old_keys, new_keys = set(old_index), set(new_index)
    same_keys = old_keys & new_keys
    added_keys = set(new_keys - old_keys)
    removed_keys = set(old_keys - new_keys)

    modified = []
    for key in sorted(same_keys):
        old_row, new_row = old_index[key], new_index[key]
        if old_row["sha256"] != new_row["sha256"] or old_row["size_bytes"] != new_row["size_bytes"]:
            modified.append({
                "split": key[0], "file_name": key[1],
                "old_sha256": old_row["sha256"], "new_sha256": new_row["sha256"],
                "old_size_bytes": int(old_row["size_bytes"]),
                "new_size_bytes": int(new_row["size_bytes"]),
            })

    # Match unique hashes across unmatched paths to distinguish a rename/move from add+remove.
    old_by_hash: dict[str, list[tuple[str, str]]] = {}
    new_by_hash: dict[str, list[tuple[str, str]]] = {}
    for key in removed_keys:
        old_by_hash.setdefault(old_index[key]["sha256"], []).append(key)
    for key in added_keys:
        new_by_hash.setdefault(new_index[key]["sha256"], []).append(key)

    renamed, moved = [], []
    for digest in sorted(set(old_by_hash) & set(new_by_hash)):
        old_matches, new_matches = old_by_hash[digest], new_by_hash[digest]
        if len(old_matches) == 1 and len(new_matches) == 1:
            old_key, new_key = old_matches[0], new_matches[0]
            entry = {"old_split": old_key[0], "old_file_name": old_key[1],
                     "new_split": new_key[0], "new_file_name": new_key[1], "sha256": digest}
            if old_key[0] == new_key[0]:
                renamed.append(entry)
            else:
                moved.append(entry)
            removed_keys.remove(old_key)
            added_keys.remove(new_key)

    annotation_diff, annotation_errors = _compare_annotations(old_documents, new_documents)
    if annotation_errors:
        return None, annotation_errors

    report = {
        "schema_version": 1,
        "hashes": {
            "old_manifest_sha256": old_manifest_sha256,
            "new_manifest_sha256": new_manifest_sha256,
            "old_coco_sha256": old_coco_sha256 or {},
            "new_coco_sha256": new_coco_sha256 or {},
        },
        "images": {
            "summary": {
                "unchanged": len(same_keys) - len(modified),
                "added": len(added_keys),
                "removed": len(removed_keys),
                "modified": len(modified),
                "renamed": len(renamed),
                "moved_between_splits": len(moved),
            },
            "added": [{"split": s, "file_name": n} for s, n in sorted(added_keys)],
            "removed": [{"split": s, "file_name": n} for s, n in sorted(removed_keys)],
            "modified": modified,
            "renamed": renamed,
            "moved_between_splits": moved,
        },
        "annotations": annotation_diff,
        "limitations": [
            "Annotation changes are matched by image file_name and semantic annotation fields; annotation IDs may change without being counted as content changes.",
            "A changed annotation is a paired removal/addition on the same image; the report does not claim semantic equivalence.",
            "Renames and split moves are inferred only when a SHA-256 occurs exactly once in each unmatched release.",
            "This report compares metadata and COCO annotations; it does not inspect image pixels or validate annotation correctness.",
        ],
    }
    return report, []


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two SMART SHELF AI COCO dataset releases")
    parser.add_argument("--old-manifest", required=True, type=Path)
    parser.add_argument("--new-manifest", required=True, type=Path)
    for split in SPLITS:
        parser.add_argument(f"--old-{split}", required=True, type=Path)
        parser.add_argument(f"--new-{split}", required=True, type=Path)
    parser.add_argument("--json-report", required=True, type=Path)
    args = parser.parse_args()

    old_rows, errors = read_manifest(args.old_manifest)
    if errors:
        print("\n".join(f"ERROR: {item}" for item in errors))
        return 2
    new_rows, errors = read_manifest(args.new_manifest)
    if errors:
        print("\n".join(f"ERROR: {item}" for item in errors))
        return 2

    old_docs, new_docs = {}, {}
    try:
        for split in SPLITS:
            old_docs[split] = json.loads(getattr(args, f"old_{split}").read_text(encoding="utf-8"))
            new_docs[split] = json.loads(getattr(args, f"new_{split}").read_text(encoding="utf-8"))
        report, errors = compare_dataset_versions(
            old_rows, new_rows, old_docs, new_docs,
            old_manifest_sha256=_file_sha256(args.old_manifest),
            new_manifest_sha256=_file_sha256(args.new_manifest),
            old_coco_sha256={s: _file_sha256(getattr(args, f"old_{s}")) for s in SPLITS},
            new_coco_sha256={s: _file_sha256(getattr(args, f"new_{s}")) for s in SPLITS},
        )
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read dataset release: {exc}")
        return 2

    if errors or report is None:
        print("\n".join(f"ERROR: {item}" for item in errors))
        return 1
    try:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: cannot write report: {exc}")
        return 2
    print(json.dumps(report["images"]["summary"], ensure_ascii=False, sort_keys=True))
    print(json.dumps(report["annotations"]["summary"], ensure_ascii=False, sort_keys=True))
    print(f"Dataset version diff written to: {args.json_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
