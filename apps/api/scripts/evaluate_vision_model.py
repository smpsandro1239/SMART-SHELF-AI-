"""Evaluate the signed ONNX provider on an approved COCO test split.

Run through app.dataset_execution so dataset approval and retention locks remain
active for the complete synchronous evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from app.coco_dataset import validate_coco_document
from app.dataset_paths import is_safe_dataset_relative_path
from app.dataset_release import load_manifest
from app.vision_evaluation import evaluate_coco_detections


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _approved_release_context(
    annotations_path: Path,
    manifest_path: Path,
    coco_document: dict[str, Any],
) -> dict[str, str]:
    if os.getenv("SMART_SHELF_DATASET_APPROVAL_STATUS") != "APPROVED":
        raise ValueError("evaluation must run inside an APPROVED dataset release consumer")
    if os.getenv("SMART_SHELF_DATASET_APPROVAL_MODE") != "inference":
        raise ValueError("vision evaluation requires a dataset release explicitly approved for inference")

    release_id = os.getenv("SMART_SHELF_DATASET_RELEASE_ID", "").strip()
    fingerprint = os.getenv("SMART_SHELF_DATASET_RELEASE_FINGERPRINT", "").strip()
    release_path_raw = os.getenv("SMART_SHELF_DATASET_RELEASE_PATH", "").strip()
    if not release_id or not _SHA256.fullmatch(fingerprint) or not release_path_raw:
        raise ValueError("approved dataset release ID, fingerprint and record path are required")

    release_path = Path(release_path_raw)
    if release_path.is_symlink() or not release_path.is_file():
        raise ValueError("approved dataset release record must be a regular non-symlink file")
    try:
        release_record = json.loads(release_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read approved dataset release record") from exc
    if (
        not isinstance(release_record, dict)
        or release_record.get("release_id") != release_id
        or release_record.get("fingerprint") != fingerprint
    ):
        raise ValueError("approved dataset release record does not match the execution context")

    approval = release_record.get("approval")
    split_hashes = approval.get("split_annotations_sha256") if isinstance(approval, dict) else None
    if (
        not isinstance(approval, dict)
        or approval.get("status") != "APPROVED"
        or approval.get("mode") != "inference"
        or not isinstance(split_hashes, dict)
        or set(split_hashes) != {"train", "val", "test"}
        or any(not isinstance(value, str) or not _SHA256.fullmatch(value) for value in split_hashes.values())
    ):
        raise ValueError("release record does not bind all approved annotation split hashes")

    if annotations_path.is_symlink() or not annotations_path.is_file():
        raise ValueError("COCO test annotations must be a regular non-symlink file")
    if _sha256_file(annotations_path) != split_hashes["test"]:
        raise ValueError("COCO test annotations do not match the approved release hash")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("dataset manifest must be a regular non-symlink file")
    if _sha256_file(manifest_path) != release_record.get("manifest_sha256"):
        raise ValueError("dataset manifest does not match the approved release hash")

    manifest_rows = load_manifest(manifest_path)
    expected_test_images = {
        row["file_name"]: row["sha256"] for row in manifest_rows if row["split"] == "test"
    }
    coco_images = coco_document.get("images")
    if not isinstance(coco_images, list):
        raise ValueError("COCO test document must contain an images array")
    actual_test_images: dict[str, str] = {}
    for image in coco_images:
        if not isinstance(image, dict):
            raise ValueError("COCO image entries must be objects")
        name, digest = image.get("file_name"), image.get("sha256")
        if not isinstance(name, str) or name in actual_test_images:
            raise ValueError("COCO test image paths must be unique strings")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError(f"COCO test image is missing a lowercase SHA-256 digest: {name}")
        actual_test_images[name] = digest
    if actual_test_images != expected_test_images:
        raise ValueError("COCO test images do not exactly match the approved test split manifest")

    return {
        "release_id": release_id,
        "release_fingerprint": fingerprint,
    }


def evaluate_approved_test_split(
    annotations_path: Path,
    images_root: Path,
    *,
    operating_threshold: float = 0.25,
) -> dict[str, Any]:
    try:
        document = json.loads(annotations_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read COCO test annotations: {exc}") from exc
    errors = validate_coco_document(document)
    if errors:
        raise ValueError("COCO test annotations are invalid: " + "; ".join(errors))
    release = _approved_release_context(annotations_path, manifest_path, document)

    from app.vision_onnx import create_provider

    provider = create_provider()
    if provider.confidence_threshold > 0.0:
        raise ValueError(
            "set VISION_CONFIDENCE_THRESHOLD=0.0 for AP evaluation; "
            "the operating threshold is configured separately"
        )

    root = images_root.resolve(strict=True)
    category_ids_by_name: dict[str, int] = {}
    for category in document["categories"]:
        name = category["name"]
        if name in category_ids_by_name:
            raise ValueError(f"duplicate COCO category name: {name}")
        category_ids_by_name[name] = category["id"]

    predictions: list[dict[str, Any]] = []
    model_versions: set[str] = set()
    seen_files: set[str] = set()
    for image_record in document["images"]:
        file_name = image_record["file_name"]
        if not isinstance(file_name, str) or not is_safe_dataset_relative_path(file_name):
            raise ValueError(f"unsafe COCO image path: {file_name}")
        if file_name in seen_files:
            raise ValueError(f"duplicate COCO image path: {file_name}")
        seen_files.add(file_name)
        image_path = (root / file_name).resolve(strict=True)
        if not image_path.is_relative_to(root) or not image_path.is_file():
            raise ValueError(f"COCO image resolves outside the approved dataset root: {file_name}")

        expected_digest = image_record.get("sha256")
        if not isinstance(expected_digest, str) or not _SHA256.fullmatch(expected_digest):
            raise ValueError(f"COCO image is missing a lowercase SHA-256 digest: {file_name}")
        if _sha256_file(image_path) != expected_digest:
            raise ValueError(f"COCO image SHA-256 mismatch: {file_name}")

        with Image.open(image_path) as image:
            if image.size != (image_record["width"], image_record["height"]):
                raise ValueError(f"COCO image dimensions do not match file: {file_name}")

        analysis = provider.analyze(image_path)
        model_versions.add(analysis.model_version)
        width, height = image_record["width"], image_record["height"]
        for detection in analysis.detections:
            category_id = category_ids_by_name.get(detection.label)
            if category_id is None:
                raise ValueError(f"model emitted a class absent from the approved COCO categories: {detection.label}")
            predictions.append({
                "image_id": image_record["id"],
                "category_id": category_id,
                "score": detection.confidence,
                "bbox": [
                    detection.x_min * width,
                    detection.y_min * height,
                    (detection.x_max - detection.x_min) * width,
                    (detection.y_max - detection.y_min) * height,
                ],
            })

    if len(model_versions) != 1:
        raise ValueError("model version changed or was missing during evaluation")
    metrics = evaluate_coco_detections(
        document,
        predictions,
        operating_threshold=operating_threshold,
    )
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_release": release,
        "model": {
            "model_version": next(iter(model_versions)),
            "detector_sha256": provider.detector_sha256,
            "embedding_sha256": provider.embedding_sha256,
            "preprocessing_version": provider.preprocessing_version,
            "confidence_floor_for_ap": provider.confidence_threshold,
        },
        "metrics": metrics,
        "scope": "approved COCO test split only; inference-only; no training or inventory writes",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", required=True, type=Path, help="Approved COCO test annotations JSON")
    parser.add_argument("--manifest", required=True, type=Path, help="Approved dataset image manifest CSV")
    parser.add_argument("--images-root", required=True, type=Path, help="Root of the approved test images")
    parser.add_argument("--output", required=True, type=Path, help="JSON evaluation report path")
    parser.add_argument("--operating-threshold", type=float, default=0.25)
    args = parser.parse_args()

    if args.output.is_symlink():
        parser.error("--output must not be a symbolic link")
    try:
        report = evaluate_approved_test_split(
            args.annotations,
            args.images_root,
            manifest_path=args.manifest,
            operating_threshold=args.operating_threshold,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Evaluation report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
