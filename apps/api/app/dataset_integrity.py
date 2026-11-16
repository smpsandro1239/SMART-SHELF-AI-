"""Cross-check COCO annotations against the SHA-256 image manifest.

This is a metadata integrity check; it does not decode images or verify annotations visually.
"""
import argparse
import copy
import csv
import json
import re
from pathlib import Path
from typing import Any

from app.coco_dataset import validate_coco_document
from app.dataset_paths import is_safe_dataset_relative_path

SPLITS = ("train", "val", "test")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def read_manifest(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"split", "file_name", "size_bytes", "sha256"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                return [], ["manifest must contain split, file_name, size_bytes and sha256 columns"]
            for line_number, row in enumerate(reader, start=2):
                split = row.get("split", "")
                file_name = row.get("file_name", "")
                size_text = row.get("size_bytes", "")
                digest = row.get("sha256", "")
                if split not in SPLITS:
                    errors.append(f"manifest line {line_number}: invalid split {split!r}")
                    continue
                if not is_safe_dataset_relative_path(file_name):
                    errors.append(
                        f"manifest line {line_number}: file_name contains path traversal "
                        "or is not a safe portable relative path"
                    )
                    continue
                try:
                    size = int(size_text)
                except (TypeError, ValueError):
                    errors.append(f"manifest line {line_number}: size_bytes must be a positive integer")
                    continue
                if size <= 0 or str(size) != str(size_text).strip():
                    errors.append(f"manifest line {line_number}: size_bytes must be a positive integer")
                    continue
                if not SHA256_PATTERN.fullmatch(digest):
                    errors.append(f"manifest line {line_number}: sha256 must be 64 lowercase hexadecimal characters")
                    continue
                rows.append({
                    "split": split,
                    "file_name": file_name,
                    "size_bytes": str(size),
                    "sha256": digest,
                })
    except OSError as exc:
        errors.append(f"cannot read manifest: {exc}")
    return rows, errors


def audit_manifest_against_coco(
    manifest_rows: list[dict[str, str]],
    split_documents: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    manifest_by_key: dict[tuple[str, str], dict[str, str]] = {}
    manifest_hashes: dict[str, tuple[str, str]] = {}

    for row in manifest_rows:
        split, file_name = row.get("split"), row.get("file_name")
        if split not in SPLITS or not isinstance(file_name, str) or not file_name:
            errors.append("manifest contains a row with invalid split or file_name")
            continue
        key = (split, file_name)
        if key in manifest_by_key:
            errors.append(f"manifest contains duplicate entry for {split}/{file_name}")
            continue
        manifest_by_key[key] = row
        digest = row.get("sha256")
        if isinstance(digest, str) and digest:
            previous = manifest_hashes.get(digest)
            if previous is not None and previous[0] != split:
                errors.append(
                    f"manifest SHA-256 is shared across {previous[0]} and {split}: {digest}"
                )
            else:
                manifest_hashes[digest] = (split, file_name)

    coco_keys: set[tuple[str, str]] = set()
    for split in SPLITS:
        if split not in split_documents:
            errors.append(f"missing COCO document for split {split}")
            continue
        document = split_documents[split]
        errors.extend(
            f"{split}: {error}" for error in validate_coco_document(document)
        )
        if not isinstance(document, dict) or not isinstance(document.get("images"), list):
            continue
        for index, image in enumerate(document["images"]):
            if not isinstance(image, dict):
                continue
            file_name = image.get("file_name")
            if not isinstance(file_name, str) or not file_name:
                continue
            key = (split, file_name)
            if key in coco_keys:
                errors.append(f"{split}: duplicate COCO file_name: {file_name}")
            coco_keys.add(key)
            manifest_row = manifest_by_key.get(key)
            if manifest_row is None:
                other_split = next(
                    (row_split for row_split, row_name in manifest_by_key if row_name == file_name),
                    None,
                )
                if other_split is not None:
                    errors.append(
                        f"{split}: COCO image {file_name} is in manifest split {other_split}, not {split}"
                    )
                else:
                    errors.append(f"{split}: COCO image missing from manifest: {file_name}")
                continue

            coco_hash = image.get("sha256")
            if coco_hash is not None and coco_hash != manifest_row["sha256"]:
                errors.append(f"{split}: SHA-256 mismatch for {file_name}")

            coco_size = image.get("file_size_bytes")
            if coco_size is not None:
                if (
                    isinstance(coco_size, bool)
                    or not isinstance(coco_size, int)
                    or coco_size != int(manifest_row["size_bytes"])
                ):
                    errors.append(f"{split}: file size mismatch for {file_name}")

    for split, file_name in sorted(set(manifest_by_key) - coco_keys):
        errors.append(f"{split}: manifest image is absent from COCO annotations: {file_name}")

    return errors



def enrich_coco_document(
    document: Any,
    manifest_rows: list[dict[str, str]],
    split: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Return a copy of a COCO document with manifest hashes and file sizes."""
    if split not in SPLITS:
        return None, [f"invalid split: {split}"]
    errors = validate_coco_document(document)
    if errors:
        return None, errors
    if not isinstance(document, dict):
        return None, ["COCO document must be an object"]

    rows_by_name: dict[str, dict[str, str]] = {}
    for row in manifest_rows:
        if row.get("split") == split:
            name = row.get("file_name")
            if not isinstance(name, str) or not name:
                errors.append("manifest contains invalid file_name")
            elif name in rows_by_name:
                errors.append(f"manifest contains duplicate entry for {split}/{name}")
            else:
                rows_by_name[name] = row
    if errors:
        return None, errors

    enriched = copy.deepcopy(document)
    for image in enriched["images"]:
        file_name = image["file_name"]
        row = rows_by_name.get(file_name)
        if row is None:
            errors.append(f"{split}: COCO image missing from manifest: {file_name}")
            continue
        image["sha256"] = row["sha256"]
        image["file_size_bytes"] = int(row["size_bytes"])

    if errors:
        return None, errors
    return enriched, []



def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-check train/val/test COCO files against a SHA-256 manifest"
    )
    parser.add_argument("--manifest", required=True, type=Path, help="CSV generated by app.dataset_manifest")
    parser.add_argument("--enriched-dir", type=Path, help="Optional directory for COCO copies enriched with SHA-256 and file size")
    for split in SPLITS:
        parser.add_argument(f"--{split}", required=True, type=Path, help=f"COCO {split} annotations")
    args = parser.parse_args()

    rows, errors = read_manifest(args.manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 2

    documents: dict[str, Any] = {}
    for split in SPLITS:
        path = getattr(args, split)
        try:
            documents[split] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: cannot read {split} COCO annotations: {exc}")
            return 2

    errors = audit_manifest_against_coco(rows, documents)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Dataset integrity check failed with {len(errors)} issue(s).")
        return 1

    if args.enriched_dir:
        try:
            args.enriched_dir.mkdir(parents=True, exist_ok=True)
            for split in SPLITS:
                enriched, enrich_errors = enrich_coco_document(documents[split], rows, split)
                if enrich_errors or enriched is None:
                    for error in enrich_errors:
                        print(f"ERROR: {split}: {error}")
                    return 1
                output_path = args.enriched_dir / f"instances_{split}.json"
                output_path.write_text(
                    json.dumps(enriched, ensure_ascii=False, indent=2) + "\\n",
                    encoding="utf-8",
                )
        except OSError as exc:
            print(f"ERROR: cannot write enriched COCO files: {exc}")
            return 2

    print(f"Dataset integrity check passed: {len(rows)} manifest image(s) match COCO.")
    if args.enriched_dir:
        print(f"Enriched COCO copies written to: {args.enriched_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
