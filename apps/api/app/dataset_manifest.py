"""Create a reproducible SHA-256 manifest for image files in dataset splits.

Example:
    python -m app.dataset_manifest \
        --train /data/images/train \
        --val /data/images/val \
        --test /data/images/test \
        --output /data/metadata/image_manifest.csv
"""
import argparse
import csv
import hashlib
from pathlib import Path
from typing import Any

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(split_roots: dict[str, Path]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []

    for split_name, root_path in split_roots.items():
        root = root_path.resolve()
        if not root.is_dir():
            errors.append(f"{split_name}: image root is not a directory: {root_path}")
            continue

        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if not path.is_file():
                continue

            resolved = path.resolve()
            if root not in resolved.parents:
                errors.append(f"{split_name}: image path escapes split root: {path}")
                continue

            try:
                size_bytes = resolved.stat().st_size
                digest = sha256_file(resolved)
            except OSError as exc:
                errors.append(f"{split_name}: cannot read {path}: {exc}")
                continue

            if size_bytes <= 0:
                errors.append(f"{split_name}: image file is empty: {path}")
                continue

            rows.append({
                "split": split_name,
                "file_name": path.relative_to(root).as_posix(),
                "size_bytes": size_bytes,
                "sha256": digest,
            })

    rows.sort(key=lambda row: (row["split"], row["file_name"]))
    return rows, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a SHA-256 manifest for image dataset splits")
    parser.add_argument("--train", required=True, type=Path, help="Training image directory")
    parser.add_argument("--val", required=True, type=Path, help="Validation image directory")
    parser.add_argument("--test", required=True, type=Path, help="Test image directory")
    parser.add_argument("--output", required=True, type=Path, help="CSV manifest output path")
    args = parser.parse_args()

    rows, errors = build_manifest({
        "train": args.train,
        "val": args.val,
        "test": args.test,
    })
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Manifest generation failed with {len(errors)} issue(s).")
        return 1

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=("split", "file_name", "size_bytes", "sha256"),
            )
            writer.writeheader()
            writer.writerows(rows)
    except OSError as exc:
        print(f"ERROR: cannot write manifest: {exc}")
        return 2

    print(f"Manifest created: {len(rows)} image file(s) -> {args.output}")
    print("Note: capture sessions and permissions must be recorded separately; they cannot be inferred from file hashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
