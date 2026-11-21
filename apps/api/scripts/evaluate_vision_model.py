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
from app.vision_evaluation import evaluate_coco_detections


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _approved_release_context() -> dict[str, str]:
    if os.getenv("SMART_SHELF_DATASET_APPROVAL_STATUS") != "APPROVED":
        raise ValueError("evaluation must run inside an APPROVED dataset release consumer")
    release_id = os.getenv("SMART_SHELF_DATASET_RELEASE_ID", "").strip()
    fingerprint = os.getenv("SMART_SHELF_DATASET_RELEASE_FINGERPRINT", "").strip()
    if not release_id or not _SHA256.fullmatch(fingerprint):
        raise ValueError("approved dataset release ID and fingerprint are required")
    return {"release_id": release_id, "release_fingerprint": fingerprint}


def evaluate_approved_test_split(
    annotations_path: Path,
    images_root: Path,
    *,
    operating_threshold: float = 0.25,
) -> dict[str, Any]:
    release = _approved_release_context()
    try:
        document = json.loads(annotations_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read COCO test annotations: {exc}") from exc
    errors = validate_coco_document(document)
    if errors:
        raise ValueError("COCO test annotations are invalid: " + "; ".join(errors))

    from app.vision_onnx import create_provider

    provider = create_provider()
    if provider.confidence_threshold > 0.001:
        raise ValueError(
            "set VISION_CONFIDENCE_THRESHOLD=0.001 for AP evaluation; "
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
    parser.add_argument("--images-root", required=True, type=Path, help="Root of the approved test images")
    parser.add_argument("--output", required=True, type=Path, help="JSON evaluation report path")
    parser.add_argument("--operating-threshold", type=float, default=0.25)
    args = parser.parse_args()

    if args.output.exists() and args.output.is_symlink():
        parser.error("--output must not be a symbolic link")
    try:
        report = evaluate_approved_test_split(
            args.annotations,
            args.images_root,
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
