"""Fenced, content-verified promotion of completed dataset job outputs.

Large file reads, hashing and copying happen before acquiring database row locks.
The final transaction revalidates the job and worker authority, performs only the
no-clobber filesystem link, and records the append-only publication.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
import os
import re
import secrets
import stat
from datetime import timezone
from pathlib import Path, PurePosixPath

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.dataset_job_leases import DatasetJobError, DatasetJobLeaseLost
from app.dataset_operational_eligibility import validate_internal_image_eligibility
from app.dataset_worker_credentials import DatasetWorkerAuthorizationError, DatasetWorkerPrincipal

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE = re.compile(r"^staging/[A-Za-z0-9._/-]{1,590}$")


class DatasetJobSourceIneligible(DatasetJobError):
    """One or more immutable job sources are no longer eligible for publication."""


class DatasetJobOutputUnavailable(FileNotFoundError):
    """Staged output is missing or cannot be safely accessed."""


class DatasetJobOutputIntegrityError(RuntimeError):
    """Staged or already-published output does not match the approved digest."""


class DatasetJobOutputConflict(DatasetJobError):
    """A different output has already been published for this job."""


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _safe_parts(reference: str, *, job_id: int, fencing_token: int) -> tuple[str, ...]:
    if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
        raise DatasetJobOutputUnavailable("staged output reference is invalid")
    parts = tuple(reference.split("/"))
    if (
        len(parts) < 4 or parts[0] != "staging"
        or parts[1] != str(job_id) or parts[2] != str(fencing_token)
        or any(part in {"", ".", ".."} for part in parts) or "\\" in reference
    ):
        raise DatasetJobOutputUnavailable("staged output must be scoped to this job and fencing token")
    return parts


def _open_dirs(root: Path, parts: tuple[str, ...], *, create: bool) -> int:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    current = os.open(root.resolve(strict=True), flags | getattr(os, "O_NOFOLLOW", 0))
    try:
        for part in parts:
            try:
                nxt = os.open(part, flags | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current)
                except FileExistsError:
                    pass
                nxt = os.open(part, flags | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
            os.close(current)
            current = nxt
        return current
    except Exception:
        os.close(current)
        raise


def _digest_existing(directory_fd: int, name: str, maximum: int) -> tuple[str, int]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise DatasetJobOutputUnavailable("published output is missing, inaccessible or a symlink") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > maximum:
            raise DatasetJobOutputUnavailable("published output is not a permitted regular file")
        digest, size = hashlib.sha256(), 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                raise DatasetJobOutputUnavailable("published output exceeds the configured size limit")
            digest.update(chunk)
        if size != info.st_size:
            raise DatasetJobOutputIntegrityError("published output changed while being hashed")
        return digest.hexdigest(), size
    finally:
        os.close(fd)


def _prepare_verified_bytes(
    *, root: Path, staged: tuple[str, ...], published: tuple[str, ...], expected_digest: str
) -> tuple[str | None, int]:
    """Verify/copy bytes to a private temp file without holding database locks.

    A pre-existing deterministic destination is fully hashed here, outside the
    final transaction. The returned temp file is in the destination directory,
    so the final no-clobber hard link is a short local filesystem operation.
    """
    source_dir = destination_dir = source_fd = temp_fd = None
    temp_name = f".promotion-{secrets.token_hex(16)}.tmp"
    maximum = settings.max_dataset_output_bytes
    try:
        destination_dir = _open_dirs(root, published[:-1], create=True)
        try:
            existing_digest, existing_size = _digest_existing(destination_dir, published[-1], maximum)
        except DatasetJobOutputUnavailable:
            existing_digest = None
            existing_size = 0
        if existing_digest is not None:
            if existing_digest != expected_digest:
                raise DatasetJobOutputIntegrityError("orphaned published output has an unexpected digest")
            return None, existing_size

        source_dir = _open_dirs(root, staged[:-1], create=False)
        source_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        source_fd = os.open(staged[-1], source_flags, dir_fd=source_dir)
        metadata = os.fstat(source_fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > maximum:
            raise DatasetJobOutputUnavailable(
                "staged output must be a non-empty regular file within the configured limit"
            )

        temp_flags = (
            os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        temp_fd = os.open(temp_name, temp_flags, 0o600, dir_fd=destination_dir)
        digest, total = hashlib.sha256(), 0
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise DatasetJobOutputUnavailable("staged output exceeds the configured size limit")
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(temp_fd, view)
                if written <= 0:
                    raise DatasetJobOutputUnavailable("could not write verified output to publication staging")
                view = view[written:]
        if total != metadata.st_size or digest.hexdigest() != expected_digest:
            raise DatasetJobOutputIntegrityError("staged output size or SHA-256 differs from the completed job")
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        prepared_name = temp_name
        temp_name = ""
        return prepared_name, total
    except DatasetJobOutputUnavailable:
        raise
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise DatasetJobOutputUnavailable("staged output or its directory is missing") from exc
        raise DatasetJobOutputUnavailable("staged output could not be safely prepared") from exc
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if destination_dir is not None and temp_name:
            try:
                os.unlink(temp_name, dir_fd=destination_dir)
            except FileNotFoundError:
                pass
        if source_fd is not None:
            os.close(source_fd)
        if destination_dir is not None:
            os.close(destination_dir)
        if source_dir is not None:
            os.close(source_dir)


def _publish_prepared_temp(
    *, root: Path, published: tuple[str, ...], temp_name: str | None
) -> None:
    if temp_name is None:
        return
    directory_fd = _open_dirs(root, published[:-1], create=False)
    try:
        os.link(
            temp_name, published[-1], src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd, follow_symlinks=False,
        )
        os.fsync(directory_fd)
        os.unlink(temp_name, dir_fd=directory_fd)
        os.fsync(directory_fd)
    except FileExistsError as exc:
        # Another publisher or an out-of-band writer won the no-clobber race.
        # Never hash a potentially large file while holding database row locks.
        raise DatasetJobOutputConflict("published destination appeared during finalization; retry promotion") from exc
    except OSError as exc:
        raise DatasetJobOutputUnavailable("prepared output could not be atomically published") from exc
    finally:
        try:
            os.unlink(temp_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def _remove_staged_output(root: Path, staged: tuple[str, ...]) -> None:
    """Best-effort post-commit cleanup; failures leave recoverable staging debris."""
    directory_fd = None
    try:
        directory_fd = _open_dirs(root, staged[:-1], create=False)
        os.unlink(staged[-1], dir_fd=directory_fd)
        os.fsync(directory_fd)
    except FileNotFoundError:
        pass
    except OSError:
        # Publication and its audit row are already committed. A later orphan
        # reconciler can safely remove this staging reference.
        pass
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _load_and_validate(
    db: Session, *, principal: DatasetWorkerPrincipal, job_id: int,
    fencing_token: int, lock_rows: bool,
):
    job_query = db.query(models.DatasetExecutionJob).filter_by(id=job_id)
    if lock_rows:
        job_query = job_query.with_for_update()
    job = job_query.populate_existing().first()
    if (
        job is None or job.status != "SUCCEEDED" or job.fencing_token != fencing_token
        or not isinstance(job.output_sha256, str) or not _SHA256.fullmatch(job.output_sha256)
        or not job.staged_output_reference
    ):
        raise DatasetJobLeaseLost("job is not successfully completed with this fencing token")

    if lock_rows:
        sources = db.query(models.DatasetExecutionJobSource).filter_by(job_id=job.id).order_by(
            models.DatasetExecutionJobSource.shelf_image_id.asc()
        ).all()
        if not sources:
            raise DatasetJobSourceIneligible("dataset job has no immutable source records")
        errors, report = validate_internal_image_eligibility(db, [{
            "source_type": "internal", "shelf_image_id": source.shelf_image_id,
            "store_id": source.store_id, "source_image_sha256": source.source_image_sha256,
        } for source in sources])
        if errors or report.get("status") != "APPROVED":
            raise DatasetJobSourceIneligible(
                "one or more dataset job sources are no longer eligible for output publication"
            )

    event = db.query(models.DatasetExecutionJobEvent).filter_by(
        job_id=job_id, event_type="SUCCEEDED"
    ).order_by(models.DatasetExecutionJobEvent.sequence_number.desc()).first()
    if (
        event is None or event.worker_id != principal.worker_id
        or event.fencing_token != fencing_token
        or (event.details or {}).get("output_sha256") != job.output_sha256
    ):
        raise DatasetJobLeaseLost("principal does not match the successful terminal fencing event")

    worker_query = db.query(models.DatasetWorker).filter_by(worker_id=principal.worker_id)
    credential_query = db.query(models.DatasetWorkerCredential).filter_by(
        credential_id=principal.credential_id, worker_id=principal.worker_id
    )
    if lock_rows:
        worker_query = worker_query.with_for_update(read=True)
        credential_query = credential_query.with_for_update(read=True)
    worker = worker_query.populate_existing().first()
    credential = credential_query.populate_existing().first()
    if (
        worker is None or worker.status != "ACTIVE" or credential is None
        or credential.revoked_at is not None or _utc(credential.expires_at) <= _utc(models.utc_now())
        or "outputs:publish" not in set(credential.scopes or [])
    ):
        raise DatasetWorkerAuthorizationError("worker credential is inactive or lacks outputs:publish")
    return job


def promote_dataset_job_output(
    db: Session, *, principal: DatasetWorkerPrincipal, job_id: int, fencing_token: int,
    derived_from_publication_id: int | None = None,
    derivation_actor_user_id: int | None = None,
    derivation_reason: str | None = None,
    authorize_derivation: Callable | None = None,
) -> models.DatasetExecutionJobOutputPublication:
    """Prepare bytes lock-free and atomically commit publication plus optional lineage."""
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
        raise DatasetJobError("job_id must be a positive integer")
    if isinstance(fencing_token, bool) or not isinstance(fencing_token, int) or fencing_token <= 0:
        raise DatasetJobError("fencing_token must be a positive integer")

    derivation_requested = derived_from_publication_id is not None
    derivation_fields = (derivation_actor_user_id, derivation_reason, authorize_derivation)
    if not derivation_requested and any(value is not None for value in derivation_fields):
        raise DatasetJobError("all derivation fields require derived_from_publication_id")
    if derivation_requested and (
        isinstance(derived_from_publication_id, bool)
        or not isinstance(derived_from_publication_id, int)
        or derived_from_publication_id <= 0
        or isinstance(derivation_actor_user_id, bool)
        or not isinstance(derivation_actor_user_id, int)
        or derivation_actor_user_id <= 0
        or not isinstance(derivation_reason, str)
        or not derivation_reason.strip()
        or len(derivation_reason.strip()) > 4000
        or not callable(authorize_derivation)
    ):
        raise DatasetJobError("derived publication requires a positive parent, active actor, reason and authorization callback")

    def lock_parent_lineage() -> None:
        if derivation_requested:
            from app.dataset_output_lineage import lock_dataset_output_lineage
            lock_dataset_output_lineage(db, publication_id=derived_from_publication_id)

    def record_derivation(publication: models.DatasetExecutionJobOutputPublication) -> None:
        if not derivation_requested:
            return
        existing_edge = db.query(models.DatasetExecutionJobOutputLineage).filter_by(
            parent_publication_id=derived_from_publication_id,
            child_publication_id=publication.id,
        ).one_or_none()
        if existing_edge is not None:
            if (
                existing_edge.actor_user_id != derivation_actor_user_id
                or existing_edge.reason != derivation_reason.strip()
            ):
                from app.dataset_output_lineage import DatasetOutputLineageConflict
                raise DatasetOutputLineageConflict("existing output derivation has different immutable metadata")
            return
        from app.dataset_output_lineage import register_dataset_output_derivation
        register_dataset_output_derivation(
            db,
            parent_publication_id=derived_from_publication_id,
            child_publication_id=publication.id,
            actor_user_id=derivation_actor_user_id,
            reason=derivation_reason,
            authorize=authorize_derivation,
        )

    temp_name = None
    staged = None
    root = Path(settings.dataset_output_storage_path)
    if not root.is_absolute():
        root = Path.cwd() / root
    try:
        # Read-only preflight authorizes access to the path but deliberately
        # takes no row locks. Roll back before hashing/copying potentially GiB.
        job = _load_and_validate(
            db, principal=principal, job_id=job_id,
            fencing_token=fencing_token, lock_rows=False,
        )
        existing = db.query(models.DatasetExecutionJobOutputPublication).filter_by(job_id=job_id).first()
        if existing is not None:
            if (
                existing.worker_id != principal.worker_id or existing.fencing_token != fencing_token
                or existing.output_sha256 != job.output_sha256
                or existing.staged_output_reference != job.staged_output_reference
            ):
                raise DatasetJobOutputConflict("job already has a different published output")
            lock_parent_lineage()
            record_derivation(existing)
            db.commit()
            return existing

        staged = _safe_parts(job.staged_output_reference, job_id=job_id, fencing_token=fencing_token)
        destination_ref = f"published/{job_id}/{fencing_token}-{job.output_sha256}.artifact"
        published = PurePosixPath(destination_ref).parts
        expected_digest = job.output_sha256
        staged_reference = job.staged_output_reference
        db.rollback()

        temp_name, byte_count = _prepare_verified_bytes(
            root=root, staged=staged, published=published, expected_digest=expected_digest,
        )

        # A derived output must lock its complete parent chain before taking
        # job/source locks, matching the consumer's publication -> job -> source order.
        lock_parent_lineage()

        # Reacquire locks only after all streaming I/O and hashing have finished.
        job = _load_and_validate(
            db, principal=principal, job_id=job_id,
            fencing_token=fencing_token, lock_rows=True,
        )
        if job.output_sha256 != expected_digest or job.staged_output_reference != staged_reference:
            raise DatasetJobLeaseLost("completed output changed during publication preparation")

        existing = db.query(models.DatasetExecutionJobOutputPublication).filter_by(job_id=job_id).first()
        if existing is not None:
            if (
                existing.worker_id != principal.worker_id or existing.fencing_token != fencing_token
                or existing.output_sha256 != expected_digest
                or existing.staged_output_reference != staged_reference
            ):
                raise DatasetJobOutputConflict("job already has a different published output")
            record_derivation(existing)
            db.commit()
            return existing

        publication = models.DatasetExecutionJobOutputPublication(
            job_id=job_id, worker_id=principal.worker_id,
            credential_id=principal.credential_id, fencing_token=fencing_token,
            output_sha256=expected_digest, staged_output_reference=staged_reference,
            published_output_reference=destination_ref, bytes_published=byte_count,
            created_at=models.utc_now(),
        )
        db.add(publication)
        db.flush()
        record_derivation(publication)
        _publish_prepared_temp(root=root, published=published, temp_name=temp_name)
        temp_name = None
        db.commit()
        db.refresh(publication)

        # Staging cleanup is intentionally after the durable audit commit.
        _remove_staged_output(root, staged)
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
    finally:
        if temp_name is not None and staged is not None:
            try:
                directory_fd = _open_dirs(root, ("published", str(job_id)), create=False)
                try:
                    os.unlink(temp_name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
