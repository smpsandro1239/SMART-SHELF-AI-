"""Transactional human review of immutable Edge task-completion declarations."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app import models


class EdgeTaskAcknowledgementReviewError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def record_edge_task_acknowledgement_review(
    db: Session, *, acknowledgement_id: int, actor: models.User,
    decision: str, reason: str, evidence_reference: str, idempotency_key: str,
) -> tuple[models.EdgeTaskAcknowledgementReview, bool]:
    """Insert one immutable review; caller owns commit/rollback."""
    if actor is None or not actor.is_active:
        raise EdgeTaskAcknowledgementReviewError("ACTOR_INACTIVE", "Active authenticated user required")
    if actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise EdgeTaskAcknowledgementReviewError("FORBIDDEN", "Supervisor role required")
    if decision not in {"APPROVED", "REJECTED"}:
        raise EdgeTaskAcknowledgementReviewError("INVALID_DECISION", "Unsupported review decision")

    identity = db.query(
        models.EdgeTaskAcknowledgement.store_id,
        models.EdgeTaskAcknowledgement.task_id,
    ).filter(models.EdgeTaskAcknowledgement.id == acknowledgement_id).first()
    if identity is None:
        raise EdgeTaskAcknowledgementReviewError("ACK_NOT_FOUND", "Acknowledgement not found")
    store_id, task_id = identity
    if actor.role != "ADMIN" and (actor.store_id is None or actor.store_id != store_id):
        raise EdgeTaskAcknowledgementReviewError("ACK_NOT_FOUND", "Acknowledgement not found")

    # Lock Task -> ACK; concurrent review requests for the same task serialize.
    task = db.query(models.ReplenishmentTask).filter(
        models.ReplenishmentTask.id == task_id,
        models.ReplenishmentTask.store_id == store_id,
    ).with_for_update().populate_existing().first()
    if task is None:
        raise EdgeTaskAcknowledgementReviewError("TASK_NOT_FOUND", "Task not found")
    acknowledgement = db.query(models.EdgeTaskAcknowledgement).filter(
        models.EdgeTaskAcknowledgement.id == acknowledgement_id,
        models.EdgeTaskAcknowledgement.store_id == store_id,
        models.EdgeTaskAcknowledgement.task_id == task_id,
    ).with_for_update().populate_existing().first()
    if acknowledgement is None:
        raise EdgeTaskAcknowledgementReviewError("ACK_NOT_FOUND", "Acknowledgement not found")
    if acknowledgement.action != "COMPLETED" or acknowledgement.result != "REVIEW_REQUIRED":
        raise EdgeTaskAcknowledgementReviewError(
            "ACK_NOT_REVIEWABLE", "Only COMPLETED acknowledgements awaiting review can be reviewed",
        )

    existing = db.query(models.EdgeTaskAcknowledgementReview).filter(
        models.EdgeTaskAcknowledgementReview.store_id == store_id,
        models.EdgeTaskAcknowledgementReview.acknowledgement_id == acknowledgement_id,
        models.EdgeTaskAcknowledgementReview.actor_user_id == actor.id,
        models.EdgeTaskAcknowledgementReview.idempotency_key == idempotency_key,
    ).first()
    if existing is not None:
        if (existing.decision, existing.reason, existing.evidence_reference) != (
            decision, reason, evidence_reference
        ):
            raise EdgeTaskAcknowledgementReviewError(
                "IDEMPOTENCY_CONFLICT", "Idempotency key was already used with different review data",
            )
        return existing, False

    review = models.EdgeTaskAcknowledgementReview(
        store_id=store_id, task_id=task_id, acknowledgement_id=acknowledgement_id,
        actor_user_id=actor.id, decision=decision, reason=reason,
        evidence_reference=evidence_reference, idempotency_key=idempotency_key,
        reviewed_at=models.utc_now(),
    )
    db.add(review)
    db.flush()
    return review, True
