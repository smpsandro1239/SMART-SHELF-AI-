"""Append-only governance history for published dataset outputs.

No physical deletion, retention deadline, HTTP route or role policy is defined
here. Callers must supply an authorization callback that explicitly returns
True; an absent or negative authorization decision fails closed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app import models

OUTPUT_GOVERNANCE_EVENT_TYPES = frozenset({
    "RESTRICTION_APPLIED", "RESTRICTION_RELEASED",
    "LEGAL_HOLD_APPLIED", "LEGAL_HOLD_RELEASED",
})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_REASON_LENGTH = 4000
_MAX_DETAILS_BYTES = 16384


class DatasetOutputGovernanceError(RuntimeError):
    """Base exception for output governance operations."""


class DatasetOutputGovernanceNotFound(DatasetOutputGovernanceError):
    """The publication does not exist."""


class DatasetOutputGovernanceAuthorizationError(DatasetOutputGovernanceError):
    """The supplied authorization policy did not positively authorize the action."""


class DatasetOutputGovernanceConflict(DatasetOutputGovernanceError):
    """The requested governance transition conflicts with the current state."""


@dataclass(frozen=True)
class DatasetOutputGovernanceState:
    publication_id: int
    sequence_number: int
    restricted: bool
    legal_hold: bool

    @property
    def blocked(self) -> bool:
        return self.restricted or self.legal_hold


AuthorizationCallback = Callable[[models.User, models.DatasetExecutionJobOutputPublication, str], bool]


def _state_from_events(publication_id: int, events) -> DatasetOutputGovernanceState:
    restricted = False
    legal_hold = False
    sequence_number = 0
    for event in events:
        sequence_number = event.sequence_number
        if event.event_type == "RESTRICTION_APPLIED":
            restricted = True
        elif event.event_type == "RESTRICTION_RELEASED":
            restricted = False
        elif event.event_type == "LEGAL_HOLD_APPLIED":
            legal_hold = True
        elif event.event_type == "LEGAL_HOLD_RELEASED":
            legal_hold = False
    return DatasetOutputGovernanceState(publication_id, sequence_number, restricted, legal_hold)


def get_output_governance_state(db: Session, *, publication_id: int) -> DatasetOutputGovernanceState:
    publication = db.query(models.DatasetExecutionJobOutputPublication.id).filter_by(id=publication_id).first()
    if publication is None:
        raise DatasetOutputGovernanceNotFound("dataset output publication was not found")
    events = db.query(models.DatasetExecutionJobOutputGovernanceEvent).filter_by(
        publication_id=publication_id
    ).order_by(models.DatasetExecutionJobOutputGovernanceEvent.sequence_number.asc()).all()
    return _state_from_events(publication_id, events)


def append_output_governance_event(
    db: Session, *, publication_id: int, event_type: str, actor_user_id: int,
    reason: str, authorize: AuthorizationCallback,
    evidence_reference: str | None = None, evidence_sha256: str | None = None,
    details: dict | None = None,
) -> models.DatasetExecutionJobOutputGovernanceEvent:
    """Append one authorized transition; the caller owns commit and rollback."""
    if event_type not in OUTPUT_GOVERNANCE_EVENT_TYPES:
        raise DatasetOutputGovernanceError("unsupported output governance event type")
    normalized_reason = reason.strip() if isinstance(reason, str) else ""
    if not normalized_reason or len(normalized_reason) > _MAX_REASON_LENGTH:
        raise DatasetOutputGovernanceError("reason must contain 1 to 4000 non-whitespace characters")
    if evidence_reference is not None:
        evidence_reference = evidence_reference.strip()
        if not evidence_reference or len(evidence_reference) > 600:
            raise DatasetOutputGovernanceError("evidence reference is invalid")
    if (evidence_reference is None) != (evidence_sha256 is None):
        raise DatasetOutputGovernanceError("evidence reference and SHA-256 must be supplied together")
    if evidence_sha256 is not None and not _SHA256.fullmatch(evidence_sha256):
        raise DatasetOutputGovernanceError("evidence SHA-256 must be 64 lowercase hexadecimal characters")
    if details is None:
        details = {}
    if not isinstance(details, dict):
        raise DatasetOutputGovernanceError("event details must be a JSON object")
    try:
        encoded = json.dumps(details, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise DatasetOutputGovernanceError("event details must be finite JSON data") from exc
    if len(encoded.encode("utf-8")) > _MAX_DETAILS_BYTES:
        raise DatasetOutputGovernanceError("event details exceed 16 KiB")

    publication = db.query(models.DatasetExecutionJobOutputPublication).filter_by(
        id=publication_id
    ).with_for_update().populate_existing().one_or_none()
    if publication is None:
        raise DatasetOutputGovernanceNotFound("dataset output publication was not found")
    actor = db.query(models.User).filter_by(id=actor_user_id).with_for_update().populate_existing().one_or_none()
    if actor is None or not actor.is_active:
        raise DatasetOutputGovernanceAuthorizationError("an active human actor is required")
    if not callable(authorize) or authorize(actor, publication, event_type) is not True:
        raise DatasetOutputGovernanceAuthorizationError("governance action was not explicitly authorized")

    current = get_output_governance_state(db, publication_id=publication_id)
    if event_type == "RESTRICTION_APPLIED" and current.restricted:
        raise DatasetOutputGovernanceConflict("output is already restricted")
    if event_type == "RESTRICTION_RELEASED" and not current.restricted:
        raise DatasetOutputGovernanceConflict("output is not restricted")
    if event_type == "LEGAL_HOLD_APPLIED" and current.legal_hold:
        raise DatasetOutputGovernanceConflict("output already has a legal hold")
    if event_type == "LEGAL_HOLD_RELEASED" and not current.legal_hold:
        raise DatasetOutputGovernanceConflict("output does not have a legal hold")

    event = models.DatasetExecutionJobOutputGovernanceEvent(
        publication_id=publication_id, sequence_number=current.sequence_number + 1,
        event_type=event_type, actor_user_id=actor_user_id, reason=normalized_reason,
        evidence_reference=evidence_reference, evidence_sha256=evidence_sha256,
        details=details, created_at=models.utc_now(),
    )
    db.add(event)
    db.flush()
    return event
