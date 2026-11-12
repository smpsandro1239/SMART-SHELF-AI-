"""Per-image human review ledger for a versioned COCO split.

The ledger records human decisions; it cannot determine semantic correctness
or authenticate the reviewer identity.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.coco_dataset import validate_coco_document

SPLITS = ("train", "val", "test")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DECISIONS = {"APPROVED", "NEEDS_CORRECTION", "REJECTED"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _annotation_digest(image_id: int, annotations: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        sorted(
            (item for item in annotations if item["image_id"] == image_id),
            key=lambda item: item["id"],
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_review_template(
    document: Any, split: str, coco_sha256: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """Create one pending review item per COCO image, bound to this COCO file."""
    if split not in SPLITS:
        return None, ["split must be train, val or test"]
    if not isinstance(coco_sha256, str) or not SHA256_PATTERN.fullmatch(coco_sha256):
        return None, ["coco_sha256 must be a 64-character lowercase SHA-256"]
    errors = validate_coco_document(document)
    if errors:
        return None, ["invalid COCO document: " + "; ".join(errors[:10])]
    annotations = document["annotations"]
    reviews = []
    for image in document["images"]:
        reviews.append({
            "image_id": image["id"],
            "file_name": image["file_name"],
            "annotations_sha256": _annotation_digest(image["id"], annotations),
            "decision": "PENDING",
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        })
    return {
        "schema_version": 1,
        "split": split,
        "coco_sha256": coco_sha256,
        "reviews": reviews,
    }, []


def validate_visual_review_record(
    record: Any, document: Any, split: str, coco_sha256: str
) -> tuple[list[str], dict[str, Any]]:
    """Require complete, unique, current and explicitly approved image reviews."""
    errors: list[str] = []
    report: dict[str, Any] = {"status": "BLOCKED", "split": split}
    if split not in SPLITS:
        return ["split must be train, val or test"], report
    if not isinstance(record, dict):
        return ["review record must be a JSON object"], report
    document_errors = validate_coco_document(document)
    if document_errors:
        return ["invalid COCO document: " + "; ".join(document_errors[:10])], report
    if record.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if record.get("split") != split:
        errors.append("review split does not match requested split")
    if record.get("coco_sha256") != coco_sha256:
        errors.append("review record is bound to a different COCO file hash")
    reviews = record.get("reviews")
    if not isinstance(reviews, list):
        errors.append("reviews must be an array")
        reviews = []

    images = {item["id"]: item for item in document["images"]}
    annotations = document["annotations"]
    seen: set[int] = set()
    approved = 0
    for index, item in enumerate(reviews):
        label = f"reviews[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        image_id = item.get("image_id")
        if isinstance(image_id, bool) or not isinstance(image_id, int):
            errors.append(f"{label}.image_id must be an integer")
            continue
        if image_id in seen:
            errors.append(f"{label}: duplicate image_id {image_id}")
            continue
        seen.add(image_id)
        image = images.get(image_id)
        if image is None:
            errors.append(f"{label}: image_id {image_id} is absent from COCO")
            continue
        if item.get("file_name") != image["file_name"]:
            errors.append(f"{label}: file_name does not match COCO image {image_id}")
        expected_annotation_hash = _annotation_digest(image_id, annotations)
        if item.get("annotations_sha256") != expected_annotation_hash:
            errors.append(f"{label}: annotations changed since review for image {image_id}")
        decision = item.get("decision")
        if decision not in DECISIONS:
            errors.append(f"{label}.decision must be APPROVED, NEEDS_CORRECTION or REJECTED")
        elif decision == "APPROVED":
            approved += 1
        else:
            errors.append(f"{label}: image {image_id} is not approved ({decision})")
        if not isinstance(item.get("reviewer"), str) or not item["reviewer"].strip():
            errors.append(f"{label}.reviewer is required")
        reviewed_at = item.get("reviewed_at")
        try:
            if not isinstance(reviewed_at, str) or not reviewed_at.strip():
                raise ValueError
            datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"{label}.reviewed_at must be an ISO 8601 timestamp")
        if not isinstance(item.get("notes", ""), str):
            errors.append(f"{label}.notes must be a string")

    missing = set(images) - seen
    for image_id in sorted(missing):
        errors.append(f"missing human review for image {image_id}")
    extra = seen - set(images)
    report.update({
        "images_in_coco": len(images),
        "review_records": len(reviews),
        "approved_images": approved,
        "missing_reviews": len(missing),
        "status": "APPROVED" if not errors else "BLOCKED",
        "errors": errors,
    })
    return errors, report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or validate a per-image human review ledger for COCO"
    )
    parser.add_argument("--coco", required=True, type=Path, help="COCO JSON split")
    parser.add_argument("--split", required=True, choices=SPLITS)
    parser.add_argument("--record", type=Path, help="Human review JSON to validate")
    parser.add_argument("--create-template", type=Path, help="Write a pending review template")
    parser.add_argument("--json-report", type=Path, help="Optional validation report")
    args = parser.parse_args()
    if bool(args.record) == bool(args.create_template):
        parser.error("provide exactly one of --record or --create-template")

    try:
        document = json.loads(args.coco.read_text(encoding="utf-8"))
        coco_digest = sha256_file(args.coco)
        if args.create_template:
            template, errors = create_review_template(document, args.split, coco_digest)
            if errors or template is None:
                raise ValueError("; ".join(errors))
            args.create_template.parent.mkdir(parents=True, exist_ok=True)
            args.create_template.write_text(
                json.dumps(template, ensure_ascii=False, indent=2) + "\\n",
                encoding="utf-8",
            )
            print(f"Review template created: {args.create_template}")
            print(f"Images requiring review: {len(template['reviews'])}")
            return 0
        record = json.loads(args.record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: cannot process review files: {exc}")
        return 2

    errors, report = validate_visual_review_record(
        record, document, args.split, coco_digest
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_report:
        try:
            args.json_report.parent.mkdir(parents=True, exist_ok=True)
            args.json_report.write_text(rendered + "\\n", encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: cannot write report: {exc}")
            return 2
    if errors:
        return 1
    print(f"Human review passed for {args.split}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
