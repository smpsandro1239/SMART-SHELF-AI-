"""Fail-closed byte consumption for published dataset job outputs.

The publication row is locked before its governance history and source lineage.
The complete file is materialized and verified before the transaction is released;
streaming/deferred reads are intentionally unsupported.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.dataset_job_output_publications import _open_dirs
from app.dataset_operational_eligibility import validate_internal_image_eligibility
from app.dataset_output_governance import get_output_governance_state

_REFERENCE = re.compile(r"^published/[1-9][0-9]*/[1-9][0-9]*-[0-9a-f]{64}\\.artifact$")


class DatasetJobOutputAccessDenied(PermissionError):
    """Authorization, governance or source eligibility denied output access."""


class DatasetJobOutputReadIntegrityError(RuntimeError):
    """Published output bytes do not match their immutable publication record."""


def _read_verified_file(
    *, root: Path, reference: str, expected_sha256: str, expected_size: int,
) -> bytes:
    if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
        raise DatasetJobOutputReadIntegrityError("published output reference is not canonical")
    parts = tuple(reference.split("/"))
    directory_fd = None
    file_fd = None
    try:
        directory_fd = _open_dirs(root, parts[:-1], create=False)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(parts[-1], flags, dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise DatasetJobOutputReadIntegrityError("published output is not a regular file")
        if info.st_size <= 0 or info.st_size != expected_size or info.st_size > settings.max_dataset_output_bytes:
            raise DatasetJobOutputReadIntegrityError("published output size differs from immutable audit")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > settings.max_dataset_output_bytes:
                raise DatasetJobOutputReadIntegrityError("published output exceeds configured size limit")
            digest.update(chunk)
            chunks.append(chunk)
        after = os.fstat(file_fd)
        if (
            total != info.st_size
            or info.st_dev != after.st_dev
            or info.st_ino != after.st_ino
            or info.st_size != after.st_size
            or info.st_mtime_ns != after.st_mtime_ns
            or digest.hexdigest() != expected_sha256
        ):
            raise DatasetJobOutputReadIntegrityError("published output changed or failed SHA-256 verification")
        return b"".join(chunks)
    except DatasetJobOutputReadIntegrityError:
        raise
    except OSError as exc:
        raise DatasetJobOutputReadIntegrityError("published output is missing or cannot be safely opened") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def consume_dataset_job_output_bytes(
    db: Session,
    *,
    publication_id: int,
    authorize: Callable[[models.DatasetExecutionJobOutputPublication, models.DatasetExecutionJob], bool],
) -> bytes:
    """Authorize and return one fully verified, currently eligible output.

    The caller owns commit/rollback and must keep this transaction open until it
    has finished handling the returned bytes. Authorization must return exactly
    True. No route, role policy, streaming response or external copy is implied.
    """
    if isinstance(publication_id, bool) or not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer")

    publication = (
        db.query(models.DatasetExecutionJobOutputPublication)
        .filter_by(id=publication_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if publication is None:
        raise LookupError("dataset output publication was not found")

    job = (
        db.query(models.DatasetExecutionJob)
        .filter_by(id=publication.job_id)
        .with_for_update()
        .populate_existing()
        .one_or_none()
    )
    if job is None or job.status != "SUCCEEDED":
        raise DatasetJobOutputAccessDenied("published output job is not in SUCCEEDED state")
    if not callable(authorize) or authorize(publication, job) is not True:
        raise DatasetJobOutputAccessDenied("output consumer was not explicitly authorized")

    governance = get_output_governance_state(db, publication_id=publication.id)
    if governance.blocked:
        reasons = []
        if governance.restricted:
            reasons.append("restriction_active")
        if governance.legal_hold:
            reasons.append("legal_hold_active")
        raise DatasetJobOutputAccessDenied("published output is blocked: " + ", ".join(reasons))

    sources = (
        db.query(models.DatasetExecutionJobSource)
        .filter_by(job_id=job.id)
        .order_by(models.DatasetExecutionJobSource.shelf_image_id.asc())
        .all()
    )
    if not sources:
        raise DatasetJobOutputAccessDenied("published output has no immutable source lineage")
    errors, report = validate_internal_image_eligibility(db, [{
        "source_type": "internal",
        "shelf_image_id": source.shelf_image_id,
        "store_id": source.store_id,
        "source_image_sha256": source.source_image_sha256,
    } for source in sources])
    if errors or report.get("status") != "APPROVED":
        raise DatasetJobOutputAccessDenied("one or more output source images are no longer eligible")

    expected_reference = (
        f"published/{job.id}/{publication.fencing_token}-{publication.output_sha256}.artifact"
    )
    if (
        publication.published_output_reference != expected_reference
        or publication.fencing_token != job.fencing_token
        or publication.output_sha256 != job.output_sha256
        or publication.bytes_published <= 0
    ):
        raise DatasetJobOutputReadIntegrityError("publication no longer matches its immutable job identity")

    root = Path(settings.dataset_output_storage_path)
    if not root.is_absolute():
        root = Path.cwd() / root
    return _read_verified_file(
        root=root,
        reference=publication.published_output_reference,
        expected_sha256=publication.output_sha256,
        expected_size=publication.bytes_published,
    )
