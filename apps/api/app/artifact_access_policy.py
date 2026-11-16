"""Fail-closed policy for consuming externally stored image derivatives.

The caller supplies records already loaded under the transaction/row locks
required by its workflow. This module deliberately performs no I/O and never
interprets an inventory snapshot as permission to delete an external object.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ArtifactAccessDecision:
    allowed: bool
    status: str
    reasons: tuple[str, ...]
    artifact_reference_id: int


def evaluate_artifact_access(
    *,
    artifact_reference_id: int,
    expected_artifact_type: str,
    expected_external_reference: str,
    expected_sha256: str | None,
    source_retention_status: str,
    source_legal_hold: bool,
    integration_status: str,
    inventory_complete: bool,
    inventory_integrity_verified: bool,
    inventory_generated_at: datetime | None,
    inventory_verified_at: datetime | None,
    inventory_max_age_seconds: int,
    inventory_entry: dict[str, Any] | None,
    latest_disposition_event: str | None,
    latest_disposition_at: datetime | None,
    now: datetime | None = None,
) -> ArtifactAccessDecision:
    """Decide whether a declared external derivative may be consumed.

    A fresh, complete, source-verified inventory must prove the exact artifact
    is present. The inventory must post-date the latest disposition event.
    Source restrictions, legal holds, revoked integrations, pending/approved
    disposal, and unknown states all deny access.
    """
    if artifact_reference_id < 1:
        raise ValueError("artifact_reference_id must be positive")
    if not expected_artifact_type.strip() or not expected_external_reference.strip():
        raise ValueError("artifact identity must be non-empty")
    if inventory_max_age_seconds < 1:
        raise ValueError("inventory_max_age_seconds must be positive")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must include a timezone")

    reasons: list[str] = []

    if source_retention_status != "ACTIVE":
        reasons.append("source_image_not_active")
    if source_legal_hold:
        reasons.append("source_image_under_legal_hold")
    if integration_status != "ACTIVE":
        reasons.append("external_integration_not_active")
    if expected_sha256 is None or expected_sha256 == "":
        reasons.append("artifact_sha256_not_declared")
    elif not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256) is None:
        reasons.append("artifact_sha256_missing_or_invalid")

    if not inventory_complete:
        reasons.append("inventory_not_complete")
    if not inventory_integrity_verified:
        reasons.append("inventory_integrity_unverified")
    if inventory_generated_at is None or inventory_verified_at is None:
        reasons.append("inventory_missing")
    else:
        generated = _utc(inventory_generated_at)
        verified = _utc(inventory_verified_at)
        current_utc = _utc(current)
        age = (current_utc - generated).total_seconds()
        verification_age = (current_utc - verified).total_seconds()
        if age < -120 or verification_age < -120:
            reasons.append("inventory_timestamp_in_future")
        elif age > inventory_max_age_seconds or verification_age > inventory_max_age_seconds:
            reasons.append("inventory_stale")

    if latest_disposition_event in {"PROPOSED", "APPROVED"}:
        reasons.append("artifact_disposition_pending_or_approved")
    elif latest_disposition_event == "DISPOSAL_ATTESTED":
        reasons.append("artifact_disposal_attested")
    elif latest_disposition_event not in {None, "REJECTED"}:
        reasons.append("artifact_disposition_state_unknown")

    if latest_disposition_at is not None and inventory_generated_at is not None:
        if _utc(inventory_generated_at) <= _utc(latest_disposition_at):
            reasons.append("inventory_predates_disposition")

    if not isinstance(inventory_entry, dict):
        reasons.append("artifact_missing_from_inventory")
    else:
        if inventory_entry.get("artifact_type") != expected_artifact_type:
            reasons.append("inventory_artifact_type_mismatch")
        if inventory_entry.get("external_reference") != expected_external_reference:
            reasons.append("inventory_external_reference_mismatch")
        if inventory_entry.get("sha256") != expected_sha256:
            reasons.append("inventory_artifact_sha256_mismatch")
        if inventory_entry.get("state") != "PRESENT":
            reasons.append("artifact_not_present")
        if inventory_entry.get("state") not in {"PRESENT", "ABSENT"}:
            reasons.append("artifact_inventory_state_unknown")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return ArtifactAccessDecision(
        allowed=not unique_reasons,
        status="APPROVED" if not unique_reasons else "BLOCKED",
        reasons=unique_reasons,
        artifact_reference_id=artifact_reference_id,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("inventory and disposition timestamps must include a timezone")
    return value.astimezone(timezone.utc)
