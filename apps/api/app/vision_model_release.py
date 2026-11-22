"""Persistent monotonic trust state for signed ONNX model releases."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import VisionModelReleaseEvent, VisionModelReleaseState


_DEPLOYMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ModelReleaseError(RuntimeError):
    """Raised when a signed model release violates persistent trust policy."""


def _validate_release(deployment_id: str, release: dict[str, Any]) -> None:
    if not isinstance(deployment_id, str) or not _DEPLOYMENT_ID.fullmatch(deployment_id):
        raise ModelReleaseError("VISION_MODEL_DEPLOYMENT_ID must be a safe non-empty identifier")
    if not isinstance(release, dict):
        raise ModelReleaseError("Verified model release metadata is invalid")
    model_id = release.get("model_id")
    key_id = release.get("key_id")
    version = release.get("release_version")
    if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
        raise ModelReleaseError("Signed model_id is invalid")
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise ModelReleaseError("Signed model key_id is invalid")
    if type(version) is not int or not 1 <= version <= 2**31 - 1:
        raise ModelReleaseError("Signed release_version is outside the supported positive integer range")
    for field in ("manifest_sha256", "detector_sha256"):
        if not isinstance(release.get(field), str) or not _SHA256.fullmatch(release[field]):
            raise ModelReleaseError(f"Verified model {field} is invalid")
    embedding_digest = release.get("embedding_sha256")
    if embedding_digest is not None and (
        not isinstance(embedding_digest, str) or not _SHA256.fullmatch(embedding_digest)
    ):
        raise ModelReleaseError("Verified model embedding_sha256 is invalid")


def _event(
    deployment_id: str,
    release: dict[str, Any],
    *,
    decision: str,
    reason: str,
) -> VisionModelReleaseEvent:
    return VisionModelReleaseEvent(
        deployment_id=deployment_id,
        model_id=release["model_id"],
        release_version=release["release_version"],
        manifest_sha256=release["manifest_sha256"],
        key_id=release["key_id"],
        decision=decision,
        reason=reason[:500],
        created_at=datetime.now(timezone.utc),
    )


def register_model_release(
    session_factory: Callable[[], Session],
    *,
    deployment_id: str,
    model_release: dict[str, Any],
) -> None:
    """Atomically advance a deployment's release high-water mark.

    Exact retries are idempotent. Lower versions, same-version manifest
    collisions and model identity changes are persisted as rejected audit
    events before the caller receives an exception.
    """
    _validate_release(deployment_id, model_release)
    db = session_factory()
    try:
        state = db.execute(
            select(VisionModelReleaseState)
            .where(VisionModelReleaseState.deployment_id == deployment_id)
            .with_for_update()
        ).scalar_one_or_none()

        if state is None:
            # Concurrent first boot is serialized by the primary key. A loser
            # re-reads the committed row and follows the normal comparison path.
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            values = {
                "deployment_id": deployment_id,
                "model_id": model_release["model_id"],
                "highest_release_version": model_release["release_version"],
                "manifest_sha256": model_release["manifest_sha256"],
                "key_id": model_release["key_id"],
                "detector_sha256": model_release["detector_sha256"],
                "embedding_sha256": model_release["embedding_sha256"],
                "updated_at": datetime.now(timezone.utc),
            }
            dialect = db.get_bind().dialect.name
            if dialect == "postgresql":
                statement = pg_insert(VisionModelReleaseState).values(**values).on_conflict_do_nothing(
                    index_elements=["deployment_id"]
                )
            elif dialect == "sqlite":
                statement = sqlite_insert(VisionModelReleaseState).values(**values).on_conflict_do_nothing(
                    index_elements=["deployment_id"]
                )
            else:
                raise ModelReleaseError(
                    f"Persistent model anti-rollback is unsupported for database dialect '{dialect}'"
                )
            insert_result = db.execute(statement)
            db.flush()
            if insert_result.rowcount == 1:
                db.add(_event(
                    deployment_id, model_release,
                    decision="ACCEPTED",
                    reason="Initial model release registered",
                ))
                db.commit()
                return
            state = db.execute(
                select(VisionModelReleaseState)
                .where(VisionModelReleaseState.deployment_id == deployment_id)
                .with_for_update()
            ).scalar_one_or_none()
            if state is None:
                raise ModelReleaseError("Persistent model release state could not be initialized")

        if state.model_id != model_release["model_id"]:
            db.add(_event(
                deployment_id, model_release,
                decision="REJECTED_MODEL_ID_CHANGE",
                reason="A deployment slot cannot change its signed model identity",
            ))
            db.commit()
            raise ModelReleaseError("Signed model identity does not match the deployment slot")

        current_version = state.highest_release_version
        candidate_version = model_release["release_version"]
        if candidate_version < current_version:
            db.add(_event(
                deployment_id, model_release,
                decision="REJECTED_ROLLBACK",
                reason=f"Release version {candidate_version} is below persisted high-water mark {current_version}",
            ))
            db.commit()
            raise ModelReleaseError(
                f"Model release rollback rejected: version {candidate_version} is below {current_version}"
            )

        if candidate_version == current_version:
            if state.manifest_sha256 != model_release["manifest_sha256"]:
                db.add(_event(
                    deployment_id, model_release,
                    decision="REJECTED_VERSION_COLLISION",
                    reason="A different signed manifest already uses this release version",
                ))
                db.commit()
                raise ModelReleaseError("A different manifest already uses the same release version")
            db.commit()
            return

        state.highest_release_version = candidate_version
        state.manifest_sha256 = model_release["manifest_sha256"]
        state.key_id = model_release["key_id"]
        state.detector_sha256 = model_release["detector_sha256"]
        state.embedding_sha256 = model_release["embedding_sha256"]
        state.updated_at = datetime.now(timezone.utc)
        db.add(_event(
            deployment_id, model_release,
            decision="ACCEPTED",
            reason="Monotonic model release upgrade accepted",
        ))
        db.commit()
    except ModelReleaseError:
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def assert_model_release_current(
    db: Session,
    *,
    deployment_id: str,
    model_release: dict[str, Any],
) -> None:
    """Lock and verify the exact current release inside the caller's transaction."""
    _validate_release(deployment_id, model_release)
    state = db.execute(
        select(VisionModelReleaseState)
        .where(VisionModelReleaseState.deployment_id == deployment_id)
        .with_for_update()
    ).scalar_one_or_none()
    if state is None:
        raise ModelReleaseError("Signed model release is not registered in persistent trust state")
    expected = (
        model_release["model_id"],
        model_release["release_version"],
        model_release["manifest_sha256"],
        model_release["key_id"],
        model_release["detector_sha256"],
        model_release["embedding_sha256"],
    )
    actual = (
        state.model_id,
        state.highest_release_version,
        state.manifest_sha256,
        state.key_id,
        state.detector_sha256,
        state.embedding_sha256,
    )
    if actual != expected:
        raise ModelReleaseError("Loaded ONNX model release is no longer current; inference is blocked")
