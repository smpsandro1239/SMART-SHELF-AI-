"""Fenced, content-verified promotion of completed dataset job outputs."""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path, PurePosixPath

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.dataset_job_leases import DatasetJobError, DatasetJobLeaseLost
from app.dataset_worker_credentials import DatasetWorkerAuthorizationError, DatasetWorkerPrincipal

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE = re.compile(r"^staging/[A-Za-z0-9._/-]{1,590}$")


class DatasetJobOutputUnavailable(FileNotFoundError):
    """Staged output is missing or cannot be safely accessed."""


class DatasetJobOutputIntegrityError(RuntimeError):
    """Staged or already-published output does not match the approved digest."""


class DatasetJobOutputConflict(DatasetJobError):
    """A different output has already been published for this job."""


def _safe_parts(reference: str) -> tuple[str, ...]:
    if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
        raise DatasetJobOutputUnavailable("staged output reference is invalid")
    path = PurePosixPath(reference)
    if path.is_absolute() or len(path.parts) < 3 or path.parts[0] != "staging":
        raise DatasetJobOutputUnavailable("staged output must be inside staging/")
    if any(part in {"", ".", ".."} for part in path.parts) or "\\" in reference:
        raise DatasetJobOutputUnavailable("staged output reference contains an unsafe component")
    return path.parts


def _open_dirs(root: Path, parts: tuple[str, ...], *, create: bool) -> int:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    current = os.open(root.resolve(strict=True), flags | nofollow)
    try:
        for part in parts:
            try:
                nxt = os.open(part, flags | nofollow, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
                nxt = os.open(part, flags | nofollow, dir_fd=current)
            os.close(current)
            current = nxt
        return current
    except Exception:
        os.close(current)
        raise


def _digest_file(directory_fd: int, name: str, maximum: int) -> tuple[str, int]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise DatasetJobOutputUnavailable("output is missing, inaccessible or a symlink") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > maximum:
            raise DatasetJobOutputUnavailable("output must be a non-empty regular file within the configured limit")
        digest, size = hashlib.sha256(), 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                raise DatasetJobOutputUnavailable("output exceeds the configured size limit")
            digest.update(chunk)
        if size != info.st_size:
            raise DatasetJobOutputIntegrityError("output changed while being hashed")
        return digest.hexdigest(), size
    finally:
        os.close(fd)


def _atomic_promote(root: Path, staged: tuple[str, ...], published: tuple[str, ...], digest: str) -> int:
    src_fd = dst_fd = None
    maximum = settings.max_dataset_output_bytes
    try:
        src_fd = _open_dirs(root, staged[:-1], create=False)
        dst_fd = _open_dirs(root, published[:-1], create=True)
        try:
            actual, size = _digest_file(src_fd, staged[-1], maximum)
            if actual != digest:
                raise DatasetJobOutputIntegrityError("staged output digest differs from the completed job")
        except DatasetJobOutputUnavailable:
            actual, size = _digest_file(dst_fd, published[-1], maximum)
            if actual != digest:
                raise DatasetJobOutputIntegrityError("orphaned published output has an unexpected digest")
            return size
        try:
            os.link(staged[-1], published[-1], src_dir_fd=src_fd, dst_dir_fd=dst_fd, follow_symlinks=False)
        except FileExistsError:
            actual, existing_size = _digest_file(dst_fd, published[-1], maximum)
            if actual != digest or existing_size != size:
                raise DatasetJobOutputIntegrityError("published destination already contains different bytes")
        except OSError as exc:
            raise DatasetJobOutputUnavailable("atomic no-clobber publication failed") from exc
        actual, published_size = _digest_file(dst_fd, published[-1], maximum)
        if actual != digest or published_size != size:
            raise DatasetJobOutputIntegrityError("published output failed post-link verification")
        os.fsync(dst_fd)
        try:
            os.unlink(staged[-1], dir_fd=src_fd)
            os.fsync(src_fd)
        except FileNotFoundError:
            pass
        return size
    finally:
        if dst_fd is not None:
            os.close(dst_fd)
        if src_fd is not None:
            os.close(src_fd)


def promote_dataset_job_output(
    db: Session, *, principal: DatasetWorkerPrincipal, job_id: int, fencing_token: int
) -> models.DatasetExecutionJobOutputPublication:
    """Publish only the output recorded by this worker's successful fencing event.

    The destination is deterministic and immutable. If a process crashes after
    the filesystem link but before SQL commit, a retry verifies and reconciles it.
    """
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
        raise DatasetJobError("job_id must be a positive integer")
    if isinstance(fencing_token, bool) or not isinstance(fencing_token, int) or fencing_token <= 0:
        raise DatasetJobError("fencing_token must be a positive integer")
    try:
        job = db.query(models.DatasetExecutionJob).filter_by(id=job_id).with_for_update().populate_existing().first()
        if (
            job is None or job.status != "SUCCEEDED" or job.fencing_token != fencing_token
            or not isinstance(job.output_sha256, str) or not _SHA256.fullmatch(job.output_sha256)
            or not job.staged_output_reference
        ):
            raise DatasetJobLeaseLost("job is not successfully completed with this fencing token")

        event = db.query(models.DatasetExecutionJobEvent).filter_by(
            job_id=job_id, event_type="SUCCEEDED"
        ).order_by(models.DatasetExecutionJobEvent.sequence_number.desc()).first()
        if (
            event is None or event.worker_id != principal.worker_id
            or event.fencing_token != fencing_token
            or (event.details or {}).get("output_sha256") != job.output_sha256
        ):
            raise DatasetJobLeaseLost("principal does not match the successful terminal fencing event")

        worker = db.query(models.DatasetWorker).filter_by(
            worker_id=principal.worker_id
        ).with_for_update(read=True).populate_existing().first()
        credential = db.query(models.DatasetWorkerCredential).filter_by(
            credential_id=principal.credential_id, worker_id=principal.worker_id
        ).with_for_update(read=True).populate_existing().first()
        if (
            worker is None or worker.status != "ACTIVE" or credential is None
            or credential.revoked_at is not None or credential.expires_at <= models.utc_now()
            or "outputs:publish" not in set(credential.scopes or [])
        ):
            raise DatasetWorkerAuthorizationError("worker credential is inactive or lacks outputs:publish")

        existing = db.query(models.DatasetExecutionJobOutputPublication).filter_by(job_id=job_id).first()
        if existing is not None:
            if (
                existing.worker_id != principal.worker_id or existing.fencing_token != fencing_token
                or existing.output_sha256 != job.output_sha256
                or existing.staged_output_reference != job.staged_output_reference
            ):
                raise DatasetJobOutputConflict("job already has a different published output")
            db.commit()
            return existing

        staged = _safe_parts(job.staged_output_reference)
        destination_ref = f"published/{job_id}/{fencing_token}-{job.output_sha256}.artifact"
        root = Path(settings.dataset_output_storage_path)
        if not root.is_absolute():
            root = Path.cwd() / root
        byte_count = _atomic_promote(
            root, staged, PurePosixPath(destination_ref).parts, job.output_sha256
        )
        publication = models.DatasetExecutionJobOutputPublication(
            job_id=job_id, worker_id=principal.worker_id,
            credential_id=principal.credential_id, fencing_token=fencing_token,
            output_sha256=job.output_sha256,
            staged_output_reference=job.staged_output_reference,
            published_output_reference=destination_ref,
            bytes_published=byte_count, created_at=models.utc_now(),
        )
        db.add(publication)
        db.commit()
        db.refresh(publication)
        return publication
    except (
        DatasetWorkerAuthorizationError, DatasetJobLeaseLost, DatasetJobOutputUnavailable,
        DatasetJobOutputIntegrityError, DatasetJobOutputConflict, DatasetJobError,
    ):
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise DatasetJobOutputConflict("publication conflicted with another promoter or database guard") from exc
    except Exception:
        db.rollback()
        raise
