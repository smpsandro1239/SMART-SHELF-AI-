"""Validate a versioned, per-image provenance sidecar for offline datasets.

This contract records declared lineage. It does not query operational retention,
authenticate reviewers, or prove that external licences are legally sufficient.
"""
import re
from typing import Any

SPLITS = ("train", "val", "test")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def _positive_id(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_provenance_manifest(
    record: Any,
    manifest_rows: list[dict[str, str]],
) -> tuple[list[str], dict[str, Any]]:
    """Require one provenance record for every exact split/name/hash manifest row."""
    errors: list[str] = []
    report: dict[str, Any] = {
        "status": "BLOCKED",
        "schema_version": record.get("schema_version") if isinstance(record, dict) else None,
        "images": 0,
    }
    if not isinstance(record, dict):
        return ["provenance manifest must be a JSON object"], report
    if type(record.get("schema_version")) is not int or record.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    entries = record.get("images")
    if not isinstance(entries, list):
        errors.append("images must be an array")
        entries = []

    expected: dict[tuple[str, str], dict[str, str]] = {}
    for index, row in enumerate(manifest_rows):
        split, file_name, digest = row.get("split"), row.get("file_name"), row.get("sha256")
        if split not in SPLITS or not isinstance(file_name, str) or not file_name or not _valid_sha256(digest):
            errors.append(f"image manifest row {index} is invalid and cannot be linked to provenance")
            continue
        key = (split, file_name)
        if key in expected:
            errors.append(f"image manifest contains duplicate entry for {split}/{file_name}")
            continue
        expected[key] = row

    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(entries):
        label = f"images[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        split, file_name = item.get("split"), item.get("file_name")
        if split not in SPLITS or not isinstance(file_name, str) or not file_name:
            errors.append(f"{label}.split and file_name must identify a manifest image")
            continue
        key = (split, file_name)
        if key in seen:
            errors.append(f"{label}: duplicate provenance entry for {split}/{file_name}")
            continue
        seen.add(key)
        manifest_row = expected.get(key)
        if manifest_row is None:
            errors.append(f"{label}: image is absent from the SHA-256 manifest: {split}/{file_name}")
        elif item.get("image_sha256") != manifest_row["sha256"]:
            errors.append(f"{label}: image_sha256 does not match manifest for {split}/{file_name}")

        source_hash = item.get("source_image_sha256")
        if not _valid_sha256(source_hash):
            errors.append(f"{label}.source_image_sha256 must be a 64-character lowercase SHA-256")

        source_type = item.get("source_type")
        if not isinstance(source_type, str) or source_type not in {"internal", "external"}:
            errors.append(f"{label}.source_type must be internal or external")
        elif source_type == "internal":
            if not _positive_id(item.get("shelf_image_id")):
                errors.append(f"{label}.shelf_image_id must be a positive integer for internal images")
            if not _positive_id(item.get("store_id")):
                errors.append(f"{label}.store_id must be a positive integer for internal images")
            for field in ("source_name", "license", "rights_reference"):
                if field in item:
                    errors.append(f"{label}.{field} is not applicable to internal images")
        elif source_type == "external":
            for field in ("source_name", "license", "rights_reference"):
                value = item.get(field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{label}.{field} is required for external images")
            for field in ("shelf_image_id", "store_id"):
                if field in item:
                    errors.append(f"{label}.{field} is not applicable to external images")

        purpose = item.get("purpose")
        if not isinstance(purpose, str) or not purpose.strip():
            errors.append(f"{label}.purpose is required")

        transformation = item.get("transformation")
        if not isinstance(transformation, dict):
            errors.append(f"{label}.transformation must be an object")
        else:
            kind = transformation.get("type")
            if not isinstance(kind, str) or kind not in {"original", "crop", "derived"}:
                errors.append(f"{label}.transformation.type must be original, crop or derived")
            elif kind == "original":
                if "parent_sha256" in transformation:
                    errors.append(f"{label}.transformation.parent_sha256 is only valid for crop/derived images")
                if _valid_sha256(source_hash) and item.get("image_sha256") != source_hash:
                    errors.append(f"{label}: original image hash must equal source_image_sha256")
            else:
                parent_hash = transformation.get("parent_sha256")
                if not _valid_sha256(parent_hash):
                    errors.append(f"{label}.transformation.parent_sha256 is required for crop/derived images")
                elif _valid_sha256(source_hash) and parent_hash != source_hash:
                    errors.append(f"{label}.transformation.parent_sha256 must match source_image_sha256")
                if not isinstance(transformation.get("operation"), str) or not transformation.get("operation", "").strip():
                    errors.append(f"{label}.transformation.operation is required for crop/derived images")

    for split, file_name in sorted(set(expected) - seen):
        errors.append(f"missing provenance entry for {split}/{file_name}")

    report.update({
        "images": len(entries),
        "manifest_images": len(expected),
        "status": "APPROVED" if not errors else "BLOCKED",
        "errors": errors,
    })
    return errors, report
