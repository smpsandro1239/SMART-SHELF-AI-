"""Run a synchronous dataset consumer while operational source-image locks remain held.

This command is a local process boundary, not a distributed lease. The child
process must finish before the database transaction is released. Detached jobs,
remote queues and cloud training APIs are deliberately not treated as covered.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Sequence

from app.dataset_release import create_release


def _contains_internal_sources(provenance_path: Path) -> bool:
    try:
        record = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read provenance manifest: {exc}") from exc
    if not isinstance(record, dict) or not isinstance(record.get("images"), list):
        raise ValueError("provenance manifest must contain an images array")
    return any(
        isinstance(item, dict) and item.get("source_type") == "internal"
        for item in record["images"]
    )


def run_release_consumer(
    manifest_path: Path,
    split_audit_path: Path,
    visual_audit_path: Path,
    provenance_path: Path,
    registry_dir: Path,
    command: Sequence[str],
    *,
    timeout_seconds: int | None = None,
) -> int:
    """Create/verify a release and run its consumer before releasing DB row locks."""
    if not command or not command[0].strip():
        raise ValueError("a consumer command is required")
    if timeout_seconds is not None and timeout_seconds < 1:
        raise ValueError("timeout_seconds must be positive")

    has_internal_sources = _contains_internal_sources(provenance_path)
    db_session = None
    try:
        if has_internal_sources:
            from app.database import SessionLocal
            db_session = SessionLocal()

        release, _created = create_release(
            manifest_path,
            split_audit_path,
            visual_audit_path,
            registry_dir,
            provenance_path=provenance_path,
            db_session=db_session,
        )

        release_path = (
            registry_dir / "releases" / f"{release['fingerprint']}.json"
        ).resolve(strict=True)
        child_env = os.environ.copy()
        child_env.update({
            "SMART_SHELF_DATASET_RELEASE_ID": str(release["release_id"]),
            "SMART_SHELF_DATASET_RELEASE_FINGERPRINT": str(release["fingerprint"]),
            "SMART_SHELF_DATASET_RELEASE_PATH": str(release_path),
        })

        completed = subprocess.run(
            list(command),
            check=False,
            timeout=timeout_seconds,
            env=child_env,
            shell=False,
        )
        return int(completed.returncode)
    finally:
        if db_session is not None:
            db_session.rollback()
            db_session.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create a quality-gated dataset release and run a synchronous "
            "consumer while source-image retention locks remain held."
        )
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--split-audit", required=True, type=Path)
    parser.add_argument("--visual-audit", required=True, type=Path)
    parser.add_argument("--provenance-manifest", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument(
        "consumer",
        nargs=argparse.REMAINDER,
        help="consumer executable and arguments; separate options with --",
    )
    args = parser.parse_args()
    command = list(args.consumer)
    if command and command[0] == "--":
        command = command[1:]
    try:
        return run_release_consumer(
            args.manifest,
            args.split_audit,
            args.visual_audit,
            args.provenance_manifest,
            args.registry,
            command,
            timeout_seconds=args.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        print("ERROR: dataset consumer exceeded its timeout")
        return 124
    except Exception as exc:
        print(f"ERROR: dataset consumer rejected: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
