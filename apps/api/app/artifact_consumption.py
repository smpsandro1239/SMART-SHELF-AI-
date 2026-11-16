"""Transactional consumption boundary for externally stored shelf-image artifacts.

A caller supplies the provider-specific byte fetcher. The fetch is executed
synchronously while the source image, store integration, artifact declaration,
inventory snapshot and disposition event are locked in one dedicated database
transaction. The function returns fully materialized bytes only; streaming
responses and deferred iterators are deliberately unsupported.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app import models
from app.artifact_access_policy import ArtifactAccessDecision, evaluate_artifact_access
from app.config import settings
from app.artifact_inventory_signing import verify_inventory_snapshot_record
from app.database import SessionLocal


class ArtifactAccessDenied(RuntimeError):
    def __init__(self, decision: ArtifactAccessDecision):
        self.decision = decision
        super().__init__("External artifact access denied: " + ", ".join(decision.reasons))


class ArtifactIntegrityError(RuntimeError):
    """The bytes returned by the provider do not match the declared SHA-256."""


def _persisted_datetime_utc(value: datetime | None) -> datetime | None:
    """Normalize DB timestamps; SQLite drops timezone metadata from UTC values."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def consume_external_artifact_bytes(
    *,
    image_id: int,
    artifact_id: int,
    store_id: int,
    fetch_bytes: Callable[[str, str], bytes],
    session_factory: Callable[[], Session] = SessionLocal,
    now: datetime | None = None,
) -> bytes:
    """Authorize and fully fetch one external artifact before releasing DB locks.

    The caller must authenticate/authorize the requesting principal for
    `store_id` before calling this service. A dedicated session is created
    here so rollback/close cannot discard unrelated caller work. Provider
    callbacks must perform the complete remote read synchronously and return
    bytes (never a stream, generator, URL or deferred handle).
    """
    if image_id < 1 or artifact_id < 1 or store_id < 1:
        raise ValueError("image_id, artifact_id and store_id must be positive")

    db = session_factory()
    try:
        image = (
            db.query(models.ShelfImage)
            .join(models.Shelf, models.ShelfImage.shelf_id == models.Shelf.id)
            .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
            .filter(
                models.ShelfImage.id == image_id,
                models.Zone.store_id == store_id,
            )
            .with_for_update(of=models.ShelfImage)
            .populate_existing()
            .first()
        )
        if image is None:
            raise LookupError("Shelf image not found")

        # Artifact declarations are append-only. Read its external-system key
        # first, then lock integration before the artifact to match the
        # inventory-ingestion lock order (image -> integration -> artifact).
        artifact_hint = (
            db.query(models.ShelfImageArtifactReference)
            .filter(
                models.ShelfImageArtifactReference.id == artifact_id,
                models.ShelfImageArtifactReference.shelf_image_id == image_id,
                models.ShelfImageArtifactReference.store_id == store_id,
            )
            .first()
        )
        if artifact_hint is None:
            raise LookupError("Artifact reference not found")

        # Discover the complete set of external systems before taking locks,
        # then lock integrations in deterministic system-name order. This keeps
        # the global order image -> integrations -> artifact references.
        reference_hints = (
            db.query(models.ShelfImageArtifactReference)
            .filter(
                models.ShelfImageArtifactReference.shelf_image_id == image_id,
                models.ShelfImageArtifactReference.store_id == store_id,
            )
            .all()
        )
        external_systems = sorted({
            reference.external_system for reference in reference_hints
        } | {artifact_hint.external_system})
        locked_integrations = (
            db.query(models.StoreExternalIntegration)
            .filter(
                models.StoreExternalIntegration.store_id == store_id,
                models.StoreExternalIntegration.external_system.in_(external_systems),
            )
            .order_by(models.StoreExternalIntegration.external_system)
            .with_for_update()
            .populate_existing()
            .all()
        )
        integrations_by_system = {
            item.external_system: item for item in locked_integrations
        }
        # Lock every declaration in deterministic primary-key order. This
        # gives the complete same-image/store parent graph a stable view and
        # avoids acquiring parent locks in request-dependent order.
        locked_references = (
            db.query(models.ShelfImageArtifactReference)
            .filter(
                models.ShelfImageArtifactReference.shelf_image_id == image_id,
                models.ShelfImageArtifactReference.store_id == store_id,
            )
            .order_by(models.ShelfImageArtifactReference.id)
            .with_for_update()
            .populate_existing()
            .all()
        )
        from app.artifact_lineage import ArtifactLineageError, resolve_artifact_parent_chain

        references_by_id = {reference.id: reference for reference in locked_references}
        try:
            lineage = resolve_artifact_parent_chain(
                artifact_id=artifact_id,
                references=references_by_id,
                expected_image_id=image_id,
                expected_store_id=store_id,
            )
        except ArtifactLineageError as exc:
            raise ArtifactAccessDenied(
                ArtifactAccessDecision(False, "BLOCKED", (str(exc),), artifact_id)
            ) from exc
        artifact = lineage[0]
        if artifact.external_system != artifact_hint.external_system:
            raise ArtifactAccessDenied(
                ArtifactAccessDecision(False, "BLOCKED", ("artifact_identity_changed",), artifact_id)
            )

        # Every ancestor is an independently governed external object. A valid
        # child snapshot must never mask a revoked integration, missing inventory,
        # or pending/completed disposition on a parent in another external system.
        now_utc = now or models.utc_now()
        # Lock all relevant snapshots and disposition events in two bounded
        # queries rather than issuing two queries per lineage node. Ordering is
        # deterministic and every row remains locked until the provider read ends.
        locked_snapshots = (
            db.query(models.ShelfImageArtifactInventorySnapshot)
            .filter(
                models.ShelfImageArtifactInventorySnapshot.shelf_image_id == image_id,
                models.ShelfImageArtifactInventorySnapshot.store_id == store_id,
                models.ShelfImageArtifactInventorySnapshot.external_system.in_(external_systems),
            )
            .order_by(
                models.ShelfImageArtifactInventorySnapshot.external_system,
                models.ShelfImageArtifactInventorySnapshot.generated_at.desc(),
                models.ShelfImageArtifactInventorySnapshot.id.desc(),
            )
            .with_for_update()
            .populate_existing()
            .all()
        )
        latest_snapshots_by_system = {}
        for snapshot in locked_snapshots:
            latest_snapshots_by_system.setdefault(snapshot.external_system, snapshot)

        lineage_reference_ids = [reference.id for reference in lineage]
        locked_events = (
            db.query(models.ShelfImageArtifactDispositionEvent)
            .filter(
                models.ShelfImageArtifactDispositionEvent.artifact_reference_id.in_(lineage_reference_ids),
                models.ShelfImageArtifactDispositionEvent.shelf_image_id == image_id,
                models.ShelfImageArtifactDispositionEvent.store_id == store_id,
            )
            .order_by(
                models.ShelfImageArtifactDispositionEvent.artifact_reference_id,
                models.ShelfImageArtifactDispositionEvent.sequence_number.desc(),
            )
            .with_for_update()
            .populate_existing()
            .all()
        )
        latest_events_by_reference = {}
        for event in locked_events:
            latest_events_by_reference.setdefault(event.artifact_reference_id, event)

        references_by_system = {}
        for reference in locked_references:
            references_by_system.setdefault(reference.external_system, []).append(reference)

        decisions = []
        for lineage_reference in lineage:
            ancestor_integration = integrations_by_system.get(
                lineage_reference.external_system
            )
            ancestor_snapshot = latest_snapshots_by_system.get(
                lineage_reference.external_system
            )
            ancestor_references = references_by_system.get(
                lineage_reference.external_system, []
            )
            inventory_integrity_verified = bool(
                ancestor_snapshot is not None
                and verify_inventory_snapshot_record(
                    snapshot=ancestor_snapshot,
                    expected_references=ancestor_references,
                    configured_keys_json=settings.artifact_inventory_hmac_keys_json,
                )
            )
            latest_event = latest_events_by_reference.get(lineage_reference.id)
            inventory_entry = None
            if ancestor_snapshot is not None:
                inventory_entry = next(
                    (
                        entry for entry in (ancestor_snapshot.inventory_manifest or [])
                        if isinstance(entry, dict)
                        and entry.get("artifact_type") == lineage_reference.artifact_type
                        and entry.get("external_reference") == lineage_reference.external_reference
                    ),
                    None,
                )
            ancestor_decision = evaluate_artifact_access(
                artifact_reference_id=lineage_reference.id,
                expected_artifact_type=lineage_reference.artifact_type,
                expected_external_reference=lineage_reference.external_reference,
                expected_sha256=lineage_reference.sha256,
                source_retention_status=image.retention_status,
                source_legal_hold=image.legal_hold,
                integration_status=(
                    ancestor_integration.status if ancestor_integration is not None else "MISSING"
                ),
                inventory_complete=bool(
                    ancestor_snapshot and ancestor_snapshot.inventory_complete
                ),
                inventory_integrity_verified=inventory_integrity_verified,
                inventory_generated_at=(
                    _persisted_datetime_utc(ancestor_snapshot.generated_at)
                    if ancestor_snapshot is not None else None
                ),
                inventory_verified_at=(
                    _persisted_datetime_utc(ancestor_snapshot.verified_at)
                    if ancestor_snapshot is not None else None
                ),
                inventory_max_age_seconds=settings.artifact_inventory_max_age_minutes * 60,
                inventory_entry=inventory_entry,
                latest_disposition_event=(
                    latest_event.event_type if latest_event is not None else None
                ),
                latest_disposition_at=(
                    _persisted_datetime_utc(latest_event.created_at)
                    if latest_event is not None else None
                ),
                now=now_utc,
            )
            decisions.append(ancestor_decision)

        # Preserve the requested artifact's decision as the public decision,
        # while adding explicit ancestor blockers to the same fail-closed result.
        target_decision = next(
            decision for decision in decisions
            if decision.artifact_reference_id == artifact.id
        )
        inherited_reasons = tuple(
            "ancestor_" + reason
            for decision in decisions
            if decision.artifact_reference_id != artifact.id and not decision.allowed
            for reason in decision.reasons
        )
        if inherited_reasons:
            decision = ArtifactAccessDecision(
                False,
                "BLOCKED",
                tuple(dict.fromkeys(target_decision.reasons + inherited_reasons)),
                artifact.id,
            )
        else:
            decision = target_decision
        if not decision.allowed:
            raise ArtifactAccessDenied(decision)
        if not artifact.sha256:
            raise ArtifactAccessDenied(
                ArtifactAccessDecision(False, "BLOCKED", ("artifact_sha256_not_declared",), artifact_id)
            )

        # Keep every row lock until the provider has completed the read and the
        # returned content has been checked. A lazy stream would outlive locks.
        payload = fetch_bytes(artifact.external_system, artifact.external_reference)
        if not isinstance(payload, bytes):
            raise TypeError("fetch_bytes must return fully materialized bytes")
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if actual_sha256 != artifact.sha256:
            raise ArtifactIntegrityError("Fetched artifact SHA-256 does not match its declaration")
        return payload
    finally:
        # The dedicated session owns this read-only transaction. Rollback
        # releases locks on both success and failure before closing the session.
        try:
            db.rollback()
        finally:
            db.close()
