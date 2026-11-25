"""Append-only lineage for derived dataset output publications."""
from __future__ import annotations
from collections.abc import Callable
from sqlalchemy import text
from sqlalchemy.orm import Session
from app import models


class DatasetOutputLineageError(RuntimeError):
    """Base error for invalid output lineage."""
class DatasetOutputLineageNotFound(DatasetOutputLineageError):
    """A referenced publication or actor does not exist."""
class DatasetOutputLineageAuthorizationError(DatasetOutputLineageError):
    """The caller did not explicitly authorize lineage registration."""
class DatasetOutputLineageConflict(DatasetOutputLineageError):
    """The requested edge is duplicate, cyclic or changed during lock acquisition."""


def _ancestor_ids(db: Session, publication_id: int) -> set[int]:
    rows = db.execute(text("""
        WITH RECURSIVE ancestors(publication_id) AS (
            SELECT parent_publication_id FROM dataset_execution_job_output_lineage
            WHERE child_publication_id = :publication_id
            UNION
            SELECT edge.parent_publication_id FROM dataset_execution_job_output_lineage edge
            JOIN ancestors a ON edge.child_publication_id = a.publication_id
        )
        SELECT publication_id FROM ancestors
        UNION SELECT :publication_id
    """), {"publication_id": publication_id}).scalars().all()
    return {int(value) for value in rows}


def lock_dataset_output_lineage(db: Session, *, publication_id: int):
    """Lock the full ancestor chain in stable ID order and verify it stayed stable."""
    if type(publication_id) is not int or publication_id < 1:
        raise ValueError("publication_id must be a positive integer")
    initial_ids = _ancestor_ids(db, publication_id)
    locked = db.query(models.DatasetExecutionJobOutputPublication).filter(
        models.DatasetExecutionJobOutputPublication.id.in_(sorted(initial_ids))
    ).order_by(models.DatasetExecutionJobOutputPublication.id.asc()).with_for_update().populate_existing().all()
    locked_ids = {item.id for item in locked}
    if not initial_ids or locked_ids != initial_ids or publication_id not in locked_ids:
        raise DatasetOutputLineageNotFound("output lineage contains a missing publication")
    if _ancestor_ids(db, publication_id) != initial_ids:
        raise DatasetOutputLineageConflict("output lineage changed while acquiring locks; retry transaction")
    return tuple(locked)


def register_dataset_output_derivation(
    db: Session, *, parent_publication_id: int, child_publication_id: int,
    actor_user_id: int, reason: str, authorize: Callable,
):
    """Record a parent -> child edge; caller owns commit/rollback.

    The callback must validate that the caller is entitled to assert the
    derivation and that evidence from the actual transformation is trustworthy.
    """
    ids = (parent_publication_id, child_publication_id, actor_user_id)
    if any(type(value) is not int or value < 1 for value in ids):
        raise ValueError("publication and actor IDs must be positive integers")
    if parent_publication_id == child_publication_id:
        raise DatasetOutputLineageConflict("an output cannot derive from itself")
    normalized_reason = reason.strip() if isinstance(reason, str) else ""
    if not normalized_reason or len(normalized_reason) > 4000:
        raise ValueError("reason must contain 1 to 4000 non-whitespace characters")
    publications = db.query(models.DatasetExecutionJobOutputPublication).filter(
        models.DatasetExecutionJobOutputPublication.id.in_(sorted({parent_publication_id, child_publication_id}))
    ).order_by(models.DatasetExecutionJobOutputPublication.id.asc()).with_for_update().populate_existing().all()
    by_id = {item.id: item for item in publications}
    parent, child = by_id.get(parent_publication_id), by_id.get(child_publication_id)
    if parent is None or child is None:
        raise DatasetOutputLineageNotFound("parent or child publication was not found")
    actor = db.query(models.User).filter_by(id=actor_user_id).with_for_update().populate_existing().one_or_none()
    if actor is None or not actor.is_active:
        raise DatasetOutputLineageAuthorizationError("an active human actor is required")
    if not callable(authorize) or authorize(actor, parent, child) is not True:
        raise DatasetOutputLineageAuthorizationError("output derivation was not explicitly authorized")
    if db.query(models.DatasetExecutionJobOutputLineage).filter_by(
        parent_publication_id=parent_publication_id, child_publication_id=child_publication_id
    ).first() is not None:
        raise DatasetOutputLineageConflict("output derivation edge already exists")
    descendants = db.execute(text("""
        WITH RECURSIVE descendants(publication_id) AS (
            SELECT child_publication_id FROM dataset_execution_job_output_lineage
            WHERE parent_publication_id = :child_id
            UNION
            SELECT edge.child_publication_id FROM dataset_execution_job_output_lineage edge
            JOIN descendants d ON edge.parent_publication_id = d.publication_id
        )
        SELECT publication_id FROM descendants
    """), {"child_id": child_publication_id}).scalars().all()
    if parent_publication_id in {int(value) for value in descendants}:
        raise DatasetOutputLineageConflict("output derivation would create a cycle")
    edge = models.DatasetExecutionJobOutputLineage(
        parent_publication_id=parent_publication_id, child_publication_id=child_publication_id,
        actor_user_id=actor_user_id, reason=normalized_reason, created_at=models.utc_now(),
    )
    db.add(edge)
    db.flush()
    return edge
