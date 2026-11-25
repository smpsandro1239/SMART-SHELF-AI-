"""Conservative, opt-in reconciliation of dataset output filesystem debris.

The command defaults to dry-run. It only removes old promotion temporaries and
staging files whose immutable publication audit row and published bytes agree.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import SessionLocal
from app.dataset_job_output_publications import (
    DatasetJobOutputUnavailable,
    _digest_existing,
    _open_dirs,
    _safe_parts,
)

_TEMPORARY_NAME = re.compile(r"^\.promotion-[0-9a-f]{32}\.tmp$")
_PUBLISHED_ARTIFACT_NAME = re.compile(r"^([1-9][0-9]*)-([0-9a-f]{64})\.artifact$")


def reconcile_dataset_job_output_files(
    db: Session,
    *,
    apply: bool = False,
    grace_seconds: int = 604800,
    now: datetime | None = None,
) -> dict:
    """Report or remove stale, provably unreferenced output files.

    Staging is removed only when an immutable successful-publication row exists,
    the destination matches its recorded digest/size, and staging itself matches
    the same digest/size. Successful jobs without a publication row are retained
    because they may still need promotion.
    """
    if not isinstance(apply, bool):
        raise ValueError("apply must be a boolean")
    if isinstance(grace_seconds, bool) or not isinstance(grace_seconds, int) or not 3600 <= grace_seconds <= 31536000:
        raise ValueError("grace_seconds must be between 3600 and 31536000")
    current = now or models.utc_now()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    cutoff = current.astimezone(timezone.utc).timestamp() - grace_seconds

    root = Path(settings.dataset_output_storage_path)
    if not root.is_absolute():
        root = Path.cwd() / root
    report = {
        "mode": "apply" if apply else "dry-run",
        "grace_seconds": grace_seconds,
        "temporary_candidates": [],
        "staging_candidates": [],
        "orphan_staging": [],
        "orphan_published": [],
        "removed": [],
        "skipped": [],
    }
    if not root.exists():
        return report

    # Publication rows are append-only. Release the read transaction before
    # filesystem traversal; reconciliation never holds database row locks.
    publications = db.query(
        models.DatasetExecutionJobOutputPublication,
        models.DatasetExecutionJob,
    ).join(
        models.DatasetExecutionJob,
        models.DatasetExecutionJob.id == models.DatasetExecutionJobOutputPublication.job_id,
    ).all()
    jobs_by_id = {
        job_id: {"status": status, "fencing_token": fencing_token}
        for job_id, status, fencing_token in db.query(
            models.DatasetExecutionJob.id,
            models.DatasetExecutionJob.status,
            models.DatasetExecutionJob.fencing_token,
        ).all()
    }
    published_staging_references = {
        publication.staged_output_reference for publication, _job in publications
    }
    published_references = {
        publication.published_output_reference for publication, _job in publications
    }
    db.rollback()

    for publication, job in publications:
        if (
            job.status != "SUCCEEDED"
            or publication.fencing_token != job.fencing_token
            or publication.output_sha256 != job.output_sha256
        ):
            report["skipped"].append({
                "reference": publication.staged_output_reference,
                "reason": "publication does not match the current successful job",
            })
            continue
        expected_destination = (
            f"published/{job.id}/{publication.fencing_token}-{publication.output_sha256}.artifact"
        )
        if publication.published_output_reference != expected_destination:
            report["skipped"].append({
                "reference": publication.staged_output_reference,
                "reason": "published destination is not canonical",
            })
            continue

        try:
            staged = _safe_parts(
                publication.staged_output_reference,
                job_id=job.id,
                fencing_token=publication.fencing_token,
            )
            published = PurePosixPath(expected_destination).parts
            published_dir = _open_dirs(root, published[:-1], create=False)
            try:
                published_digest, published_size = _digest_existing(
                    published_dir, published[-1], settings.max_dataset_output_bytes
                )
            finally:
                os.close(published_dir)
            if published_digest != publication.output_sha256 or published_size != publication.bytes_published:
                report["skipped"].append({
                    "reference": publication.staged_output_reference,
                    "reason": "published bytes do not match the immutable audit row",
                })
                continue

            staged_dir = _open_dirs(root, staged[:-1], create=False)
            try:
                staged_info = os.stat(staged[-1], dir_fd=staged_dir, follow_symlinks=False)
                if not stat.S_ISREG(staged_info.st_mode):
                    raise DatasetJobOutputUnavailable("staged output is not a regular file")
                if staged_info.st_mtime > cutoff:
                    continue
                staged_digest, staged_size = _digest_existing(
                    staged_dir, staged[-1], settings.max_dataset_output_bytes
                )
                after_info = os.stat(staged[-1], dir_fd=staged_dir, follow_symlinks=False)
                if (
                    staged_info.st_dev != after_info.st_dev
                    or staged_info.st_ino != after_info.st_ino
                    or staged_info.st_size != after_info.st_size
                    or staged_info.st_mtime_ns != after_info.st_mtime_ns
                ):
                    report["skipped"].append({
                        "reference": publication.staged_output_reference,
                        "reason": "staging file changed during reconciliation",
                    })
                    continue
                if staged_digest != publication.output_sha256 or staged_size != publication.bytes_published:
                    report["skipped"].append({
                        "reference": publication.staged_output_reference,
                        "reason": "staging bytes do not match the immutable publication",
                    })
                    continue

                candidate = {
                    "reference": publication.staged_output_reference,
                    "bytes": staged_size,
                    "modified_at": datetime.fromtimestamp(staged_info.st_mtime, timezone.utc).isoformat(),
                }
                report["staging_candidates"].append(candidate)
                if apply:
                    os.unlink(staged[-1], dir_fd=staged_dir)
                    os.fsync(staged_dir)
                    report["removed"].append(publication.staged_output_reference)
            finally:
                os.close(staged_dir)
        except (OSError, DatasetJobOutputUnavailable, ValueError) as exc:
            report["skipped"].append({
                "reference": publication.staged_output_reference,
                "reason": str(exc) or "filesystem entry is unavailable",
            })

    # Temporary promotion files have no durable database reference. Their
    # random, private names and age threshold make them eligible for cleanup.
    published_root_fd = None
    try:
        published_root_fd = _open_dirs(root, ("published",), create=False)
        directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        for job_directory in os.listdir(published_root_fd):
            try:
                directory_info = os.stat(
                    job_directory, dir_fd=published_root_fd, follow_symlinks=False
                )
                if not job_directory.isdigit() or not stat.S_ISDIR(directory_info.st_mode):
                    continue
                job_directory_fd = os.open(
                    job_directory, directory_flags | nofollow, dir_fd=published_root_fd
                )
            except (FileNotFoundError, NotADirectoryError, OSError):
                continue
            try:
                for name in os.listdir(job_directory_fd):
                    if not _TEMPORARY_NAME.fullmatch(name):
                        continue
                    try:
                        info = os.stat(name, dir_fd=job_directory_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(info.st_mode) or info.st_mtime > cutoff:
                        continue
                    reference = f"published/{job_directory}/{name}"
                    candidate = {
                        "reference": reference,
                        "bytes": info.st_size,
                        "modified_at": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                    }
                    report["temporary_candidates"].append(candidate)
                    if apply:
                        os.unlink(name, dir_fd=job_directory_fd)
                        os.fsync(job_directory_fd)
                        report["removed"].append(reference)
            finally:
                os.close(job_directory_fd)
    except (FileNotFoundError, NotADirectoryError):
        pass
    finally:
        if published_root_fd is not None:
            os.close(published_root_fd)

    # Inventory canonical final artifacts that have no immutable SQL publication
    # row. A recent file may be between filesystem promotion and SQL commit; the
    # grace period avoids noisy reports for in-flight work. This inventory is
    # strictly report-only, including with --apply: bytes may be recoverable.
    orphan_published_root_fd = None
    try:
        orphan_published_root_fd = _open_dirs(root, ("published",), create=False)
        directory_flags = (
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        for job_name in os.listdir(orphan_published_root_fd):
            if not job_name.isdigit() or str(int(job_name)) != job_name:
                continue
            try:
                directory_info = os.stat(
                    job_name, dir_fd=orphan_published_root_fd, follow_symlinks=False
                )
                if not stat.S_ISDIR(directory_info.st_mode):
                    continue
                job_fd = os.open(job_name, directory_flags, dir_fd=orphan_published_root_fd)
            except OSError:
                continue
            try:
                job_id = int(job_name)
                job_state = jobs_by_id.get(job_id)
                for name in os.listdir(job_fd):
                    match = _PUBLISHED_ARTIFACT_NAME.fullmatch(name)
                    if match is None:
                        continue
                    reference = f"published/{job_name}/{name}"
                    if reference in published_references:
                        continue
                    try:
                        info = os.stat(name, dir_fd=job_fd, follow_symlinks=False)
                    except OSError:
                        continue
                    if not stat.S_ISREG(info.st_mode) or info.st_mtime > cutoff:
                        continue
                    report["orphan_published"].append({
                        "reference": reference,
                        "bytes": info.st_size,
                        "output_sha256": match.group(2),
                        "modified_at": datetime.fromtimestamp(
                            info.st_mtime, timezone.utc
                        ).isoformat(),
                        "job_status": job_state["status"] if job_state else None,
                        "reason": "missing_publication_audit_row",
                        "cleanup": "report_only",
                    })
            finally:
                os.close(job_fd)
    except (FileNotFoundError, NotADirectoryError):
        pass
    finally:
        if orphan_published_root_fd is not None:
            os.close(orphan_published_root_fd)

    # Inventory stale staging files without a publication record. These
    # bytes may belong to a worker that is still writing, a retryable SUCCEEDED
    # job, a revoked/failed execution, or an unknown job. Fencing in SQL does
    # not prove filesystem quiescence, so this pass is deliberately report-only
    # even when --apply was requested.
    staging_root_fd = None
    try:
        staging_root_fd = _open_dirs(root, ("staging",), create=False)
        directory_flags = (
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        for job_name in os.listdir(staging_root_fd):
            if not job_name.isdigit():
                continue
            try:
                job_info = os.stat(job_name, dir_fd=staging_root_fd, follow_symlinks=False)
                if not stat.S_ISDIR(job_info.st_mode):
                    continue
                job_fd = os.open(job_name, directory_flags, dir_fd=staging_root_fd)
            except OSError:
                continue
            try:
                for token_name in os.listdir(job_fd):
                    if not token_name.isdigit():
                        continue
                    try:
                        token_info = os.stat(token_name, dir_fd=job_fd, follow_symlinks=False)
                        if not stat.S_ISDIR(token_info.st_mode):
                            continue
                        token_fd = os.open(token_name, directory_flags, dir_fd=job_fd)
                    except OSError:
                        continue
                    try:
                        job_id = int(job_name)
                        token = int(token_name)
                        job_state = jobs_by_id.get(job_id)
                        for name in os.listdir(token_fd):
                            reference = f"staging/{job_name}/{token_name}/{name}"
                            if reference in published_staging_references:
                                continue
                            try:
                                info = os.stat(name, dir_fd=token_fd, follow_symlinks=False)
                            except OSError:
                                continue
                            if not stat.S_ISREG(info.st_mode) or info.st_mtime > cutoff:
                                continue
                            if job_state is None:
                                reason = "unknown_job"
                                status = None
                            elif token != job_state["fencing_token"]:
                                reason = "stale_fencing_token_worker_quiescence_unproven"
                                status = job_state["status"]
                            elif job_state["status"] == "SUCCEEDED":
                                reason = "succeeded_without_publication_may_be_retried"
                                status = job_state["status"]
                            elif job_state["status"] in {"FAILED", "REVOKED", "CANCELLED"}:
                                reason = "terminal_job_worker_quiescence_unproven"
                                status = job_state["status"]
                            else:
                                reason = "worker_may_still_be_active"
                                status = job_state["status"]
                            report["orphan_staging"].append({
                                "reference": reference,
                                "bytes": info.st_size,
                                "modified_at": datetime.fromtimestamp(
                                    info.st_mtime, timezone.utc
                                ).isoformat(),
                                "job_status": status,
                                "reason": reason,
                                "cleanup": "blocked_until_filesystem_quiescence_is_proven",
                            })
                    finally:
                        os.close(token_fd)
            finally:
                os.close(job_fd)
    except (FileNotFoundError, NotADirectoryError):
        pass
    finally:
        if staging_root_fd is not None:
            os.close(staging_root_fd)

    report["orphan_staging_count"] = len(report["orphan_staging"])
    report["orphan_published_count"] = len(report["orphan_published"])
    report["candidate_count"] = (
        len(report["temporary_candidates"]) + len(report["staging_candidates"])
    )
    report["removed_count"] = len(report["removed"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile stale dataset output temporaries and already-published staging files."
    )
    parser.add_argument(
        "--grace-hours", type=int, default=168,
        help="minimum file age before cleanup (1–8760 hours; default: 168)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="delete verified candidates; without this flag the command is read-only",
    )
    args = parser.parse_args()
    if not 1 <= args.grace_hours <= 8760:
        parser.error("--grace-hours must be between 1 and 8760")

    with SessionLocal() as db:
        report = reconcile_dataset_job_output_files(
            db, apply=args.apply, grace_seconds=args.grace_hours * 3600
        )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
