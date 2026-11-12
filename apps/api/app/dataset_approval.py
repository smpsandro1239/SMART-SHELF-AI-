"""Dataset release gate: combines provenance, privacy sign-off and dataset audits.

The gate verifies declared review decisions and reproducible dataset artifacts.
It does not authenticate reviewers or provide legal advice.
"""
import argparse
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.dataset_audit import audit_splits
from app.dataset_integrity import audit_manifest_against_coco, read_manifest
from app.dataset_quality import analyze_dataset_quality
from app.dataset_review import sha256_file, validate_visual_review_record

SPLITS = ("train", "val", "test")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_timestamp(value: Any) -> bool:
    if not _non_empty(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _approved_review(value: Any, label: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label}: review record is required")
        return
    if value.get("approved") is not True:
        errors.append(f"{label}: explicit approval is required")
    if not _non_empty(value.get("reviewer")):
        errors.append(f"{label}: reviewer is required")
    if not _valid_timestamp(value.get("reviewed_at")):
        errors.append(f"{label}: reviewed_at must be an ISO 8601 timestamp")


def validate_release_record(record: Any, mode: str = "training") -> list[str]:
    """Validate release metadata and explicit approvals without trusting defaults."""
    errors: list[str] = []
    if mode not in {"training", "inference"}:
        return ["mode must be 'training' or 'inference'"]
    if not isinstance(record, dict):
        return ["release record must be a JSON object"]

    dataset = record.get("dataset")
    if not isinstance(dataset, dict):
        errors.append("dataset: object is required")
        dataset = {}
    for field in ("name", "version", "responsible", "storage_location"):
        if not _non_empty(dataset.get(field)):
            errors.append(f"dataset.{field} is required")
    if not _valid_timestamp(dataset.get("created_at")):
        errors.append("dataset.created_at must be an ISO 8601 timestamp")
    if not isinstance(dataset.get("manifest_sha256"), str) or not SHA256_PATTERN.fullmatch(
        dataset.get("manifest_sha256", "")
    ):
        errors.append("dataset.manifest_sha256 must be a 64-character lowercase SHA-256")

    purpose = record.get("purpose")
    if not isinstance(purpose, dict):
        errors.append("purpose: object is required")
        purpose = {}
    for field in ("task", "allowed_uses", "excluded_uses"):
        value = purpose.get(field)
        if not _non_empty(value) and not (
            isinstance(value, list) and value and all(_non_empty(item) for item in value)
        ):
            errors.append(f"purpose.{field} must be a non-empty string or list of strings")

    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance: object is required")
        provenance = {}
    if provenance.get("collection_authorized") is not True:
        errors.append("provenance.collection_authorized must be explicitly true")
    for field in ("source_organizations", "usage_rights", "dataset_license", "annotation_tool"):
        if not _non_empty(provenance.get(field)):
            errors.append(f"provenance.{field} is required")

    privacy = record.get("privacy")
    if not isinstance(privacy, dict):
        errors.append("privacy: object is required")
        privacy = {}
    for field in ("exif_gps_removed", "personal_data_reviewed"):
        if privacy.get(field) is not True:
            errors.append(f"privacy.{field} must be explicitly true")
    for field in ("retention_and_access", "incident_review"):
        if not _non_empty(privacy.get(field)):
            errors.append(f"privacy.{field} is required")

    quality = record.get("quality")
    if not isinstance(quality, dict):
        errors.append("quality: object is required")
        quality = {}
    for field in ("annotation_protocol", "quality_review_summary"):
        if not _non_empty(quality.get(field)):
            errors.append(f"quality.{field} is required")
    review_percent = quality.get("second_annotator_review_percent")
    if (
        isinstance(review_percent, bool)
        or not isinstance(review_percent, (int, float))
        or not math.isfinite(review_percent)
        or not 0 <= review_percent <= 100
    ):
        errors.append("quality.second_annotator_review_percent must be a number between 0 and 100")

    approvals = record.get("approvals")
    if not isinstance(approvals, dict):
        errors.append("approvals: object is required")
        approvals = {}
    _approved_review(approvals.get("technical"), "approvals.technical", errors)
    _approved_review(approvals.get("privacy_legal"), "approvals.privacy_legal", errors)

    if mode == "training" and record.get("approved_for_training") is not True:
        errors.append("approved_for_training must be explicitly true")
    if mode == "inference":
        if record.get("approved_for_training") is not True:
            errors.append("approved_for_training must be true before operational inference")
        if record.get("approved_for_operational_inference") is not True:
            errors.append("approved_for_operational_inference must be explicitly true")
        _approved_review(approvals.get("operational_inference"), "approvals.operational_inference", errors)
        model = record.get("model")
        if not isinstance(model, dict):
            errors.append("model: evaluation record is required for operational inference")
            model = {}
        for field in ("name", "version", "weights_license", "evaluation_protocol"):
            if not _non_empty(model.get(field)):
                errors.append(f"model.{field} is required for operational inference")
        metrics = model.get("metrics_by_class")
        if not isinstance(metrics, dict) or not metrics:
            errors.append("model.metrics_by_class must contain measured per-class metrics")
        else:
            for class_name, values in metrics.items():
                if not _non_empty(class_name) or not isinstance(values, dict):
                    errors.append("model.metrics_by_class entries must be named metric objects")
                    continue
                for metric in ("precision", "recall", "ap50"):
                    value = values.get(metric)
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(value)
                        or not 0 <= value <= 1
                    ):
                        errors.append(
                            f"model.metrics_by_class.{class_name}.{metric} must be a measured value between 0 and 1"
                        )
    return errors


def run_release_gate(
    record: Any,
    manifest_path: Path,
    split_paths: dict[str, Path],
    *,
    mode: str = "training",
    review_paths: dict[str, Path] | None = None,
    require_visual_review: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    """Run metadata checks plus COCO, split, manifest and quality audits."""
    errors = validate_release_record(record, mode)
    report: dict[str, Any] = {"mode": mode, "status": "BLOCKED", "checks": {}}
    if require_visual_review and (
        review_paths is None or any(split not in review_paths for split in SPLITS)
    ):
        errors.append("visual review records are required for train, val and test")
    if review_paths is not None and any(split not in review_paths for split in SPLITS):
        errors.append("when supplied, visual review records must include train, val and test")
    if errors:
        report["checks"]["release_record"] = {"passed": False, "errors": errors}
        return errors, report

    try:
        manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    except OSError as exc:
        errors.append(f"cannot read manifest: {exc}")
        report["checks"]["manifest_file"] = {"passed": False, "errors": errors[:]}
        return errors, report

    expected_digest = record["dataset"]["manifest_sha256"]
    if manifest_digest != expected_digest:
        errors.append("dataset.manifest_sha256 does not match the supplied manifest file")
    report["checks"]["manifest_file"] = {
        "passed": manifest_digest == expected_digest,
        "sha256": manifest_digest,
    }

    manifest_rows, manifest_errors = read_manifest(manifest_path)
    errors.extend(manifest_errors)
    report["checks"]["manifest_format"] = {
        "passed": not manifest_errors,
        "errors": manifest_errors,
        "images": len(manifest_rows),
    }

    documents: dict[str, Any] = {}
    for split in SPLITS:
        path = split_paths.get(split)
        if path is None:
            errors.append(f"missing path for {split} COCO annotations")
            continue
        try:
            documents[split] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot read {split} COCO annotations: {exc}")

    if len(documents) == len(SPLITS):
        integrity_errors = audit_manifest_against_coco(manifest_rows, documents)
        errors.extend(integrity_errors)
        report["checks"]["manifest_coco_integrity"] = {
            "passed": not integrity_errors,
            "errors": integrity_errors,
        }

        split_errors, split_report = audit_splits(documents)
        errors.extend(split_errors)
        report["checks"]["split_leakage"] = {
            "passed": not split_errors,
            "errors": split_errors,
            "report": split_report,
        }

        quality_errors, quality_report = analyze_dataset_quality(documents)
        errors.extend(quality_errors)
        report["checks"]["dataset_quality"] = {
            "passed": not quality_errors,
            "errors": quality_errors,
            "report": quality_report,
        }

        if review_paths is not None:
            review_errors: list[str] = []
            review_details: dict[str, Any] = {}
            for split in SPLITS:
                try:
                    review_record = json.loads(review_paths[split].read_text(encoding="utf-8"))
                    coco_digest = sha256_file(split_paths[split])
                    split_errors, split_report = validate_visual_review_record(
                        review_record, documents[split], split, coco_digest
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    split_errors = [f"cannot read {split} visual review record: {exc}"]
                    split_report = {"status": "BLOCKED", "split": split}
                review_errors.extend(f"{split}: {error}" for error in split_errors)
                review_details[split] = split_report
            errors.extend(review_errors)
            report["checks"]["visual_review"] = {
                "passed": not review_errors,
                "errors": review_errors,
                "splits": review_details,
            }
    elif require_visual_review:
        report["checks"]["visual_review"] = {
            "passed": False,
            "errors": ["visual review could not run because one or more COCO splits are unavailable"],
        }

    report["status"] = "APPROVED" if not errors else "BLOCKED"
    report["errors"] = errors
    return errors, report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate dataset training/inference release on provenance, approvals and reproducible audits"
    )
    parser.add_argument("--release-record", required=True, type=Path, help="Completed dataset release JSON")
    parser.add_argument("--manifest", required=True, type=Path, help="SHA-256 CSV image manifest")
    parser.add_argument("--train", required=True, type=Path, help="COCO training annotations")
    parser.add_argument("--val", required=True, type=Path, help="COCO validation annotations")
    parser.add_argument("--test", required=True, type=Path, help="COCO test annotations")
    parser.add_argument("--mode", choices=("training", "inference"), default="training")
    parser.add_argument("--require-visual-review", action="store_true", help="Require approved per-image reviews for all three splits")
    parser.add_argument("--review-train", type=Path, help="Human review ledger for train split")
    parser.add_argument("--review-val", type=Path, help="Human review ledger for val split")
    parser.add_argument("--review-test", type=Path, help="Human review ledger for test split")
    parser.add_argument("--json-report", type=Path, help="Optional JSON gate report")
    args = parser.parse_args()
    review_args = (args.review_train, args.review_val, args.review_test)
    if any(review_args) and not all(review_args):
        parser.error("provide all of --review-train, --review-val and --review-test")
    if args.require_visual_review and not all(review_args):
        parser.error("--require-visual-review requires all three review record paths")

    try:
        record = json.loads(args.release_record.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read release record: {exc}")
        return 2

    errors, report = run_release_gate(
        record,
        args.manifest,
        {"train": args.train, "val": args.val, "test": args.test},
        mode=args.mode,
        review_paths=(
            {"train": args.review_train, "val": args.review_val, "test": args.review_test}
            if all(review_args) else None
        ),
        require_visual_review=args.require_visual_review,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json_report:
        try:
            args.json_report.parent.mkdir(parents=True, exist_ok=True)
            args.json_report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"ERROR: cannot write gate report: {exc}")
            return 2
    if errors:
        for error in errors:
            print(f"BLOCKED: {error}")
        return 1
    print(f"Dataset release gate passed for {args.mode}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
