"""Fail-closed validation helpers for external artifact parent lineage."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ArtifactLineageError(ValueError):
    """An external artifact has an incomplete or inconsistent parent chain."""


def resolve_artifact_parent_chain(
    *,
    artifact_id: int,
    references: Mapping[int, Any],
    expected_image_id: int,
    expected_store_id: int,
) -> tuple[Any, ...]:
    """Return the artifact and its ancestors, rejecting broken or cyclic links.

    The caller is responsible for loading the mapping in a transaction with
    suitable row locks. This helper is intentionally pure and fail-closed.
    """
    if artifact_id < 1 or expected_image_id < 1 or expected_store_id < 1:
        raise ValueError("artifact and lineage scope identifiers must be positive")

    chain: list[Any] = []
    visited: set[int] = set()
    current_id: int | None = artifact_id

    while current_id is not None:
        if current_id in visited:
            raise ArtifactLineageError("artifact_parent_cycle")
        visited.add(current_id)

        current = references.get(current_id)
        if current is None:
            raise ArtifactLineageError("artifact_parent_missing")
        if getattr(current, "id", None) != current_id:
            raise ArtifactLineageError("artifact_parent_identity_mismatch")
        if getattr(current, "shelf_image_id", None) != expected_image_id:
            raise ArtifactLineageError("artifact_parent_image_mismatch")
        if getattr(current, "store_id", None) != expected_store_id:
            raise ArtifactLineageError("artifact_parent_store_mismatch")

        parent_id = getattr(current, "parent_reference_id", None)
        if parent_id is not None and (
            not isinstance(parent_id, int) or parent_id < 1
        ):
            raise ArtifactLineageError("artifact_parent_reference_invalid")

        chain.append(current)
        current_id = parent_id

    return tuple(chain)
