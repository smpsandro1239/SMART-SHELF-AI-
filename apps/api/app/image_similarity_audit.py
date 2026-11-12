"""Detect visually near-duplicate images crossing dataset splits.

Uses a 64-bit difference hash (dHash) and a BK-tree so lookup cost is
pruned by Hamming distance instead of comparing every image pair.
This is a screening signal, not a semantic duplicate detector.
"""
import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
SPLITS = ("train", "val", "test")


def difference_hash(path: Path) -> int:
    """Return a 64-bit dHash after EXIF orientation correction."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(image.getdata())
    value = 0
    for row in range(8):
        offset = row * 9
        for column in range(8):
            value = (value << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
    return value


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


class BKTree:
    """BK-tree for integer hashes with Hamming distance."""

    def __init__(self) -> None:
        self.root: dict[str, Any] | None = None

    def add(self, value: int, item: dict[str, Any]) -> None:
        if self.root is None:
            self.root = {"value": value, "items": [item], "children": {}}
            return
        node = self.root
        while True:
            distance = hamming_distance(value, node["value"])
            if distance == 0:
                node["items"].append(item)
                return
            child = node["children"].get(distance)
            if child is None:
                node["children"][distance] = {"value": value, "items": [item], "children": {}}
                return
            node = child

    def search(self, value: int, radius: int) -> list[tuple[int, dict[str, Any]]]:
        matches: list[tuple[int, dict[str, Any]]] = []
        if self.root is None:
            return matches
        pending = [self.root]
        while pending:
            node = pending.pop()
            distance = hamming_distance(value, node["value"])
            if distance <= radius:
                matches.extend((distance, item) for item in node["items"])
            lower, upper = distance - radius, distance + radius
            pending.extend(
                child for edge, child in node["children"].items()
                if lower <= edge <= upper
            )
        return matches


def audit_visual_duplicates(
    split_roots: dict[str, Path], *, max_distance: int = 6
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    report: dict[str, Any] = {
        "algorithm": "dHash-64",
        "max_hamming_distance": max_distance,
        "images_scanned": 0,
        "cross_split_matches": [],
        "within_split_matches": [],
        "unreadable_images": [],
    }
    if isinstance(max_distance, bool) or not isinstance(max_distance, int) or not 0 <= max_distance <= 64:
        return ["max_distance must be an integer between 0 and 64"], report

    tree = BKTree()
    for split in SPLITS:
        root_path = split_roots.get(split)
        if root_path is None or not root_path.is_dir():
            errors.append(f"{split}: image root is not a directory: {root_path}")
            continue
        for path in sorted(root_path.rglob("*")):
            if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
                continue
            try:
                digest = difference_hash(path)
            except (OSError, ValueError) as exc:
                report["unreadable_images"].append({
                    "split": split,
                    "file_name": path.relative_to(root_path).as_posix(),
                    "reason": str(exc),
                })
                errors.append(f"{split}: cannot decode image {path}: {exc}")
                continue

            current = {
                "split": split,
                "file_name": path.relative_to(root_path).as_posix(),
                "dhash": f"{digest:016x}",
            }
            for distance, previous in tree.search(digest, max_distance):
                match = {
                    "distance": distance,
                    "left": previous,
                    "right": current,
                }
                if previous["split"] != split:
                    report["cross_split_matches"].append(match)
                else:
                    report["within_split_matches"].append(match)
            tree.add(digest, current)
            report["images_scanned"] += 1

    if report["cross_split_matches"]:
        errors.append(
            f"{len(report['cross_split_matches'])} visually near-duplicate pair(s) cross dataset splits"
        )
    return errors, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Find visually near-duplicate images across dataset splits")
    for split in SPLITS:
        parser.add_argument(f"--{split}", required=True, type=Path, help=f"{split} image directory")
    parser.add_argument("--max-distance", type=int, default=6, help="Maximum dHash Hamming distance (0-64)")
    parser.add_argument("--json-report", type=Path, help="Optional JSON report output path")
    args = parser.parse_args()
    errors, report = audit_visual_duplicates(
        {split: getattr(args, split) for split in SPLITS},
        max_distance=args.max_distance,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_report:
        try:
            args.json_report.parent.mkdir(parents=True, exist_ok=True)
            args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: cannot write JSON report: {exc}")
            return 2
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("Visual duplicate audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
