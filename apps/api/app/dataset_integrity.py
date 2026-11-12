"""Cross-check COCO annotations against the SHA-256 image manifest.

This is a metadata integrity check; it does not decode images or verify annotations visually.
"""
import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from app.coco_dataset import validate_coco_document

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
                if not file_name or file_name.startswith("/") or "\x00" in file_name:
                    errors.append(f"manifest line {line_number}: invalid relative file_name")
                    continue
                parts = Path(file_name).parts
                if ".." in parts:
                    errors.append(f"manifest line {line_number}: file_name contains path traversal")
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-check train/val/test COCO files against a SHA-256 manifest"
    )
    parser.add_argument("--manifest", required=True, type=Path, help="CSV generated by app.dataset_manifest")
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

    print(f"Dataset integrity check passed: {len(rows)} manifest image(s) match COCO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
