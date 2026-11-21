"""Run an approved dataset consumer while source-image retention locks remain held.

This is a synchronous local-process boundary, not a distributed lease. The
release gate, release fingerprinting and consumer run share one DB transaction
for internal images. Detached jobs, remote queues and cloud training APIs are
not covered by this transaction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Sequence

from app.dataset_release import create_release, sha256_file


def _read_provenance(provenance_path: Path) -> dict[str, Any]:
    try:
        record = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read provenance manifest: {exc}") from exc
    if not isinstance(record, dict) or not isinstance(record.get("images"), list):
        raise ValueError("provenance manifest must contain an images array")
    return record


def _approval_digest(report: dict[str, Any]) -> str:
    canonical = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_release_consumer(
    manifest_path: Path,
    split_audit_path: Path,
    visual_audit_path: Path,
    provenance_path: Path,
    registry_dir: Path,
    command: Sequence[str],
    *,
    release_record_path: Path,
    split_paths: dict[str, Path],
    timeout_seconds: int | None = None,
    mode: str = "training",
    review_paths: dict[str, Path] | None = None,
    require_visual_review: bool = False,
) -> int:
    """Approve, fingerprint and consume a release before releasing source locks."""
    if not command or not isinstance(command[0], str) or not command[0].strip():
        raise ValueError("a consumer command is required")
    if timeout_seconds is not None and timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")
    if mode not in {"training", "inference"}:
        raise ValueError("mode must be training or inference")
    if set(split_paths) != {"train", "val", "test"}:
        raise ValueError("split_paths must contain train, val and test")

    provenance_record = _read_provenance(provenance_path)
    try:
        release_record_bytes = release_record_path.read_bytes()
        release_record = json.loads(release_record_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read approved release record: {exc}") from exc

    has_internal_sources = any(
        isinstance(item, dict) and item.get("source_type") == "internal"
        for item in provenance_record["images"]
    )
    db_session = None
    try:
        if has_internal_sources:
            from app.database import SessionLocal
            db_session = SessionLocal()

        from app.dataset_approval import run_release_gate

        split_hashes_before = {
            split: sha256_file(path) for split, path in sorted(split_paths.items())
        }
        gate_errors, gate_report = run_release_gate(
            release_record, manifest_path, split_paths,
            provenance_path=provenance_path, db_session=db_session, mode=mode,
            review_paths=review_paths, require_visual_review=require_visual_review,
        )
        split_hashes_after = {
            split: sha256_file(path) for split, path in sorted(split_paths.items())
        }
        if split_hashes_before != split_hashes_after:
            raise ValueError("dataset annotation files changed while the approval gate was running")
        if gate_errors or gate_report.get("status") != "APPROVED":
            reasons = gate_errors or gate_report.get("errors") or ["approval gate did not approve the dataset"]
            raise ValueError("dataset approval gate rejected: " + "; ".join(reasons))

        approval_evidence = {
            "status": "APPROVED",
            "mode": mode,
            "record_sha256": hashlib.sha256(release_record_bytes).hexdigest(),
            "gate_report_sha256": _approval_digest(gate_report),
            "split_annotations_sha256": split_hashes_after,
        }
        release, _created = create_release(
            manifest_path, split_audit_path, visual_audit_path, registry_dir,
            provenance_path=provenance_path, db_session=db_session,
            approval_evidence=approval_evidence,
        )
        release_path = (registry_dir / "releases" / f"{release['fingerprint']}.json").resolve(strict=True)
        child_env = os.environ.copy()
        child_env.update({
            "SMART_SHELF_DATASET_RELEASE_ID": str(release["release_id"]),
            "SMART_SHELF_DATASET_RELEASE_FINGERPRINT": str(release["fingerprint"]),
            "SMART_SHELF_DATASET_RELEASE_PATH": str(release_path),
            "SMART_SHELF_DATASET_APPROVAL_STATUS": approval_evidence["status"],
            "SMART_SHELF_DATASET_APPROVAL_MODE": approval_evidence["mode"],
            "SMART_SHELF_DATASET_APPROVAL_RECORD_SHA256": approval_evidence["record_sha256"],
            "SMART_SHELF_DATASET_APPROVAL_REPORT_SHA256": approval_evidence["gate_report_sha256"],
        })
        completed = subprocess.run(
            list(command), check=False, timeout=timeout_seconds,
            env=child_env, shell=False,
        )
        return int(completed.returncode)
    finally:
        if db_session is not None:
            db_session.rollback()
            db_session.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate an approved dataset, create an approval-bound release and run a synchronous consumer."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--split-audit", required=True, type=Path)
    parser.add_argument("--visual-audit", required=True, type=Path)
    parser.add_argument("--provenance-manifest", required=True, type=Path)
    parser.add_argument("--release-record", required=True, type=Path)
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--val", required=True, type=Path)
    parser.add_argument("--test", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--mode", choices=("training", "inference"), default="training")
    parser.add_argument("--require-visual-review", action="store_true")
    parser.add_argument("--review-train", type=Path)
    parser.add_argument("--review-val", type=Path)
    parser.add_argument("--review-test", type=Path)
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("consumer", nargs=argparse.REMAINDER,
                        help="consumer executable and arguments; separate options with --")
    args = parser.parse_args()
    review_args = (args.review_train, args.review_val, args.review_test)
    if any(review_args) and not all(review_args):
        parser.error("provide all of --review-train, --review-val and --review-test")
    if args.require_visual_review and not all(review_args):
        parser.error("--require-visual-review requires all three review record paths")
    command = list(args.consumer)
    if command and command[0] == "--":
        command = command[1:]
    try:
        return run_release_consumer(
            args.manifest, args.split_audit, args.visual_audit, args.provenance_manifest,
            args.registry, command, release_record_path=args.release_record,
            split_paths={"train": args.train, "val": args.val, "test": args.test},
            timeout_seconds=args.timeout_seconds, mode=args.mode,
            review_paths=({"train": args.review_train, "val": args.review_val, "test": args.review_test}
                          if all(review_args) else None),
            require_visual_review=args.require_visual_review,
        )
    except subprocess.TimeoutExpired:
        print("ERROR: dataset consumer exceeded its timeout")
        return 124
    except Exception as exc:
        print(f"ERROR: dataset consumer rejected: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
