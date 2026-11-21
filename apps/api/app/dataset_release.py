"""Create immutable, quality-gated dataset release records.

A release is created only when the split-leakage and visual-similarity
reports explicitly contain status='passed' and an empty errors list.
The release fingerprint binds the normalized image manifest and provenance sidecar hash.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.dataset_provenance import validate_provenance_manifest
from app.dataset_operational_eligibility import validate_internal_image_eligibility
from app.dataset_paths import is_safe_dataset_relative_path

REQUIRED_SPLITS = {"train", "val", "test"}
REQUIRED_COLUMNS = {"split", "file_name", "size_bytes", "sha256"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError("manifest must contain split,file_name,size_bytes,sha256 columns")
        rows = []
        seen = set()
        for line_number, row in enumerate(reader, start=2):
            split = row["split"]
            file_name = row["file_name"]
            digest = row["sha256"].lower()
            try:
                size = int(row["size_bytes"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid size_bytes at CSV line {line_number}") from exc
            if split not in REQUIRED_SPLITS:
                raise ValueError(f"unsupported split at CSV line {line_number}: {split}")
            if not is_safe_dataset_relative_path(file_name):
                raise ValueError(f"unsafe file_name at CSV line {line_number}: {file_name}")
            if size <= 0:
                raise ValueError(f"size_bytes must be positive at CSV line {line_number}")
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError(f"invalid SHA-256 at CSV line {line_number}")
            key = (split, file_name)
            if key in seen:
                raise ValueError(f"duplicate manifest entry: {split}/{file_name}")
            seen.add(key)
            rows.append({
                "split": split,
                "file_name": file_name,
                "size_bytes": size,
                "sha256": digest,
            })
    if not rows:
        raise ValueError("manifest contains no image entries")
    missing = REQUIRED_SPLITS - {row["split"] for row in rows}
    if missing:
        raise ValueError(f"manifest is missing split(s): {', '.join(sorted(missing))}")
    rows.sort(key=lambda row: (row["split"], row["file_name"]))
    return rows


def _load_passed_report(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label} report: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} report must be a JSON object")
    if payload.get("status") != "passed" or payload.get("errors") != []:
        raise ValueError(f"{label} quality gate has not passed; regenerate the report")
    return payload, sha256_file(path)


def create_release(
    manifest_path: Path,
    split_audit_path: Path,
    visual_audit_path: Path,
    registry_dir: Path,
    *,
    provenance_path: Path,
    db_session: Any | None = None,
    min_images_per_split: int = 1,
    min_class_instances: int = 0,
    approval_evidence: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    if approval_evidence is not None:
        if not isinstance(approval_evidence, dict):
            raise ValueError("approval_evidence must be an object")
        if approval_evidence.get("status") != "APPROVED":
            raise ValueError("approval_evidence must have APPROVED status")
        if approval_evidence.get("mode") not in {"training", "inference"}:
            raise ValueError("approval_evidence mode must be training or inference")
        for field in ("record_sha256", "gate_report_sha256"):
            digest = approval_evidence.get(field)
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)):
                raise ValueError(f"approval_evidence.{field} must be a lowercase SHA-256 digest")
        split_hashes = approval_evidence.get("split_annotations_sha256")
        if split_hashes is not None:
            if not isinstance(split_hashes, dict) or set(split_hashes) != REQUIRED_SPLITS:
                raise ValueError("approval_evidence.split_annotations_sha256 must contain train, val and test")
            for split_name, digest in split_hashes.items():
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(character not in "0123456789abcdef" for character in digest)):
                    raise ValueError(
                        f"approval_evidence.split_annotations_sha256.{split_name} must be a lowercase SHA-256 digest"
                    )

    rows = load_manifest(manifest_path)
    try:
        provenance_record = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read provenance manifest: {exc}") from exc
    provenance_errors, provenance_report = validate_provenance_manifest(provenance_record, rows)
    if provenance_errors:
        raise ValueError("provenance manifest rejected: " + "; ".join(provenance_errors))

    operational_errors, operational_report = validate_internal_image_eligibility(
        db_session,
        provenance_record.get("images", []) if isinstance(provenance_record, dict) else [],
    )
    if operational_errors:
        raise ValueError("operational image eligibility rejected: " + "; ".join(operational_errors))

    split_report, split_report_hash = _load_passed_report(split_audit_path, "split audit")
    visual_report, visual_report_hash = _load_passed_report(visual_audit_path, "visual similarity audit")

    if min_images_per_split < 1:
        raise ValueError("min_images_per_split must be at least 1")
    if min_class_instances < 0:
        raise ValueError("min_class_instances cannot be negative")

    counts = Counter(row["split"] for row in rows)
    for split in sorted(REQUIRED_SPLITS):
        if counts.get(split, 0) < min_images_per_split:
            raise ValueError(
                f"{split} contains {counts.get(split, 0)} image(s); "
                f"minimum is {min_images_per_split}"
            )

    split_summaries = split_report.get("splits", {})
    if not isinstance(split_summaries, dict):
        raise ValueError("split audit report has invalid class-balance data")
    category_ids = sorted({
        category_id
        for summary in split_summaries.values()
        if isinstance(summary, dict) and isinstance(summary.get("classes"), dict)
        for category_id in summary["classes"]
    })
    class_instance_counts: dict[str, dict[str, int]] = {}
    class_balance_warnings: list[str] = []
    for category_id in category_ids:
        per_split: dict[str, int] = {}
        category_name = str(category_id)
        for split in sorted(REQUIRED_SPLITS):
            summary = split_summaries.get(split, {})
            classes = summary.get("classes", {}) if isinstance(summary, dict) else {}
            details = classes.get(category_id, {}) if isinstance(classes, dict) else {}
            instances = details.get("instances", 0) if isinstance(details, dict) else 0
            if isinstance(instances, bool) or not isinstance(instances, int) or instances < 0:
                raise ValueError(f"invalid instance count for class {category_id} in {split}")
            per_split[split] = instances
            if instances < min_class_instances:
                raise ValueError(
                    f"class {category_id} has {instances} instance(s) in {split}; "
                    f"minimum is {min_class_instances}"
                )
            if instances == 0:
                class_balance_warnings.append(
                    f"class {category_id} has no annotated instances in {split}"
                )
        class_instance_counts[category_name] = per_split

    provenance_digest = sha256_file(provenance_path)
    identity_payload = {"images": rows, "provenance_sha256": provenance_digest}
    if approval_evidence is not None:
        identity_payload["approval"] = approval_evidence
    canonical = json.dumps(
        identity_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    release = {
        "schema_version": 1,
        "release_id": f"ds-{fingerprint[:16]}",
        "fingerprint": fingerprint,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": sha256_file(manifest_path),
        "provenance": {
            "schema_version": provenance_report.get("schema_version"),
            "manifest_sha256": sha256_file(provenance_path),
            "image_count": provenance_report.get("images", 0),
            "status": provenance_report.get("status"),
            "operational_eligibility": {
                "status": operational_report.get("status"),
                "internal_images": operational_report.get("internal_images", 0),
                "checked_images": operational_report.get("checked_images", 0),
            },
        },
        "image_count": len(rows),
        "images_by_split": {split: counts.get(split, 0) for split in sorted(REQUIRED_SPLITS)},
        "quality_gates": {
            "split_integrity": {
                "status": "passed",
                "report_sha256": split_report_hash,
                "cross_split": split_report.get("cross_split", {}),
            },
            "visual_similarity": {
                "status": "passed",
                "report_sha256": visual_report_hash,
                "algorithm": visual_report.get("algorithm"),
                "max_hamming_distance": visual_report.get("max_hamming_distance"),
                "images_scanned": visual_report.get("images_scanned"),
            },
        },
        "class_balance": {
            "by_split": split_summaries,
            "instances_by_class_and_split": class_instance_counts,
            "warnings": class_balance_warnings,
            "minimum_instances_per_class_per_split": min_class_instances,
        },
    }
    if approval_evidence is not None:
        release["approval"] = dict(approval_evidence)

    releases_dir = registry_dir / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)
    destination = releases_dir / f"{fingerprint}.json"
    serialized = json.dumps(release, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if destination.is_symlink():
        raise RuntimeError("registry integrity error: release path must not be a symlink")
    try:
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
        created = True
    except FileExistsError:
        if destination.is_symlink():
            raise RuntimeError("registry integrity error: release path must not be a symlink")
        try:
            existing = json.loads(destination.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("registry integrity error: existing release is unreadable") from exc
        if not isinstance(existing, dict) or existing.get("fingerprint") != fingerprint:
            raise RuntimeError("registry collision: existing release fingerprint differs")
        existing_created_at = existing.get("created_at")
        if not isinstance(existing_created_at, str):
            raise RuntimeError("registry integrity error: existing release timestamp is missing")
        try:
            parsed_created_at = datetime.fromisoformat(existing_created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeError("registry integrity error: existing release timestamp is invalid") from exc
        if parsed_created_at.tzinfo is None:
            raise RuntimeError("registry integrity error: existing release timestamp must include a timezone")
        expected_immutable = dict(release)
        existing_immutable = dict(existing)
        expected_immutable.pop("created_at", None)
        existing_immutable.pop("created_at", None)
        if existing_immutable != expected_immutable:
            raise RuntimeError("registry integrity error: existing release metadata differs from validated inputs")
        release = existing
        created = False
    return release, created


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an immutable quality-gated dataset release")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--split-audit", required=True, type=Path)
    parser.add_argument("--visual-audit", required=True, type=Path)
    parser.add_argument("--provenance-manifest", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--min-images-per-split", type=int, default=1)
    parser.add_argument("--min-class-instances", type=int, default=0)
    args = parser.parse_args()
    db_session = None
    try:
        try:
            provenance_record = json.loads(args.provenance_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            provenance_record = None
        has_internal_sources = (
            isinstance(provenance_record, dict)
            and isinstance(provenance_record.get("images"), list)
            and any(
                isinstance(item, dict) and item.get("source_type") == "internal"
                for item in provenance_record["images"]
            )
        )
        if has_internal_sources:
            from app.database import SessionLocal
            db_session = SessionLocal()

        release, created = create_release(
            args.manifest, args.split_audit, args.visual_audit, args.registry,
            provenance_path=args.provenance_manifest,
            db_session=db_session,
            min_images_per_split=args.min_images_per_split,
            min_class_instances=args.min_class_instances,
        )
    except Exception as exc:
        print(f"ERROR: dataset release rejected: {exc}")
        return 1
    finally:
        if db_session is not None:
            db_session.rollback()
            db_session.close()
    print(json.dumps(release, ensure_ascii=False, indent=2))
    print("Dataset release created." if created else "Dataset release already exists (idempotent).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
