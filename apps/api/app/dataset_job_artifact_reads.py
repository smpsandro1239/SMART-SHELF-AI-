"""Per-request, lease-fenced reads of internal dataset job source images."""

from __future__ import annotations

import hashlib
import os
import stat
from datetime import timezone
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.dataset_job_leases import (
    DatasetJobLeaseLost,
    _owned_lease,
)
from app.dataset_operational_eligibility import validate_internal_image_eligibility
from app.dataset_worker_credentials import (
    DatasetWorkerAuthorizationError,
    DatasetWorkerPrincipal,
    require_dataset_worker_scope,
)


class DatasetJobSourceNotFound(LookupError):
    """The requested image is not an immutable source of this job."""


class DatasetJobSourceIneligible(PermissionError):
    """The job source is no longer eligible for worker consumption."""


class DatasetJobSourceUnavailable(FileNotFoundError):
    """The stored source file is unavailable or outside its tenant directory."""


class DatasetJobSourceIntegrityError(RuntimeError):
    """The stored bytes differ from the immutable source digest or size."""


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _read_regular_file_without_symlinks(
    *, storage_path: str, store_id: int, expected_size: int, maximum_size: int
) -> bytes:
    """Read a store file through pinned directory descriptors and O_NOFOLLOW."""
    raw_path = Path(storage_path)
    if ".." in raw_path.parts:
        raise DatasetJobSourceUnavailable("stored image path contains traversal")
    root = Path(settings.image_storage_path)
    if not root.is_absolute():
        root = Path.cwd() / root
    try:
        root = root.resolve(strict=True)
        store_root = root / str(store_id)
        candidate = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path
        candidate = Path(os.path.abspath(candidate))
        relative = candidate.relative_to(store_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DatasetJobSourceUnavailable("stored image is outside its owning store") from exc
    if not relative.parts or expected_size <= 0 or expected_size > maximum_size:
        raise DatasetJobSourceUnavailable("stored image metadata is outside permitted limits")

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    base_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    root_fd = store_fd = current_fd = file_fd = None
    try:
        root_fd = os.open(root, base_flags | directory_flag)
        store_fd = os.open(str(store_id), base_flags | directory_flag | nofollow, dir_fd=root_fd)
        current_fd = store_fd
        for component in relative.parts[:-1]:
            next_fd = os.open(component, base_flags | directory_flag | nofollow, dir_fd=current_fd)
            if current_fd != store_fd:
                os.close(current_fd)
            current_fd = next_fd
        file_fd = os.open(relative.parts[-1], base_flags | nofollow, dir_fd=current_fd)
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != expected_size:
            raise DatasetJobSourceIntegrityError("stored image type or size does not match metadata")
        chunks = []
        remaining = maximum_size + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != expected_size:
            raise DatasetJobSourceIntegrityError("stored image size changed while being read")
        return payload
    except DatasetJobSourceUnavailable:
        raise
    except DatasetJobSourceIntegrityError:
        raise
    except OSError as exc:
        raise DatasetJobSourceUnavailable("stored image path is unavailable or contains a symlink") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if current_fd is not None and current_fd != store_fd:
            os.close(current_fd)
        if store_fd is not None:
            os.close(store_fd)
        if root_fd is not None:
            os.close(root_fd)


def read_dataset_job_source_bytes(
    db: Session,
    *,
    principal: DatasetWorkerPrincipal,
    job_id: int,
    fencing_token: int,
    shelf_image_id: int,
) -> bytes:
    """Read one job-bound source while lease, tenant and retention locks are held.

    Bytes are fully materialised and SHA-256 checked before the audit record is
    committed and the bytes are returned. No stream, path or storage URL escapes.
    """
    try:
        require_dataset_worker_scope(principal, required_scope="artifacts:read")
        _owned_lease(
            db, job_id=job_id, worker_id=principal.worker_id,
            fencing_token=fencing_token,
        )
        source = db.query(models.DatasetExecutionJobSource).filter_by(
            job_id=job_id, shelf_image_id=shelf_image_id
        ).first()
        if source is None:
            raise DatasetJobSourceNotFound("image is not an approved source of this job")

        errors, report = validate_internal_image_eligibility(
            db,
            [{
                "source_type": "internal",
                "shelf_image_id": source.shelf_image_id,
                "store_id": source.store_id,
                "source_image_sha256": source.source_image_sha256,
            }],
        )
        if errors or report.get("status") != "APPROVED":
            raise DatasetJobSourceIneligible("dataset job source is no longer eligible")

        image = (
            db.query(models.ShelfImage)
            .filter(models.ShelfImage.id == shelf_image_id)
            .with_for_update()
            .populate_existing()
            .first()
        )
        if (
            image is None
            or image.retention_status != "ACTIVE"
            or image.legal_hold
            or image.sha256 != source.source_image_sha256
        ):
            raise DatasetJobSourceIneligible("dataset job source changed or is restricted")

        # Revalidate the persisted worker and credential after acquiring the
        # source locks. This closes the gap between HTTP authentication and the
        # actual byte read if the credential was revoked or the worker disabled.
        worker = db.query(models.DatasetWorker).filter_by(
            worker_id=principal.worker_id
        ).with_for_update(read=True).populate_existing().first()
        credential = db.query(models.DatasetWorkerCredential).filter_by(
            credential_id=principal.credential_id,
            worker_id=principal.worker_id,
        ).with_for_update(read=True).populate_existing().first()
        now = models.utc_now()
        if (
            worker is None
            or worker.status != "ACTIVE"
            or credential is None
            or credential.revoked_at is not None
            or _utc(credential.expires_at) <= _utc(now)
            or "artifacts:read" not in set(credential.scopes or [])
        ):
            raise DatasetWorkerAuthorizationError(
                "worker credential is no longer active or lacks artifacts:read"
            )

        payload = _read_regular_file_without_symlinks(
            storage_path=image.storage_path,
            store_id=source.store_id,
            expected_size=image.file_size_bytes,
            maximum_size=settings.max_image_upload_bytes,
        )
        actual_digest = hashlib.sha256(payload).hexdigest()
        if actual_digest != source.source_image_sha256:
            raise DatasetJobSourceIntegrityError("stored image SHA-256 does not match the approved source")

        db.add(models.DatasetExecutionJobArtifactRead(
            job_id=job_id,
            shelf_image_id=shelf_image_id,
            worker_id=principal.worker_id,
            credential_id=principal.credential_id,
            fencing_token=fencing_token,
            source_image_sha256=actual_digest,
            bytes_read=len(payload),
            created_at=models.utc_now(),
        ))
        db.commit()
        return payload
    except (DatasetWorkerAuthorizationError, DatasetJobLeaseLost,
            DatasetJobSourceNotFound, DatasetJobSourceIneligible,
            DatasetJobSourceUnavailable, DatasetJobSourceIntegrityError):
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise DatasetJobSourceIneligible(
            "worker, credential, lease or source eligibility changed during the read"
        ) from exc
    except Exception:
        db.rollback()
        raise
