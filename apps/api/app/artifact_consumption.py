"""Transactional consumption boundary for externally stored shelf-image artifacts.

A caller supplies the provider-specific byte fetcher. The fetch is executed
synchronously while the source image, store integration, artifact declaration,
inventory snapshot and disposition event are locked in one dedicated database
transaction. The function returns fully materialized bytes only; streaming
responses and deferred iterators are deliberately unsupported.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
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

        integration = (
            db.query(models.StoreExternalIntegration)
            .filter(
                models.StoreExternalIntegration.store_id == store_id,
                models.StoreExternalIntegration.external_system == artifact_hint.external_system,
            )
            .with_for_update()
            .populate_existing()
            .first()
        )

        artifact = (
            db.query(models.ShelfImageArtifactReference)
            .filter(
                models.ShelfImageArtifactReference.id == artifact_id,
                models.ShelfImageArtifactReference.shelf_image_id == image_id,
                models.ShelfImageArtifactReference.store_id == store_id,
            )
            .with_for_update()
            .populate_existing()
            .first()
        )
        if artifact is None:
            raise LookupError("Artifact reference not found")
        if artifact.external_system != artifact_hint.external_system:
            raise ArtifactAccessDenied(
                ArtifactAccessDecision(False, "BLOCKED", ("artifact_identity_changed",), artifact_id)
            )

        snapshot = (
            db.query(models.ShelfImageArtifactInventorySnapshot)
            .filter(
                models.ShelfImageArtifactInventorySnapshot.shelf_image_id == image_id,
                models.ShelfImageArtifactInventorySnapshot.store_id == store_id,
                models.ShelfImageArtifactInventorySnapshot.external_system == artifact.external_system,
            )
            .order_by(
                models.ShelfImageArtifactInventorySnapshot.generated_at.desc(),
                models.ShelfImageArtifactInventorySnapshot.id.desc(),
            )
            .with_for_update()
            .populate_existing()
            .first()
        )
        inventory_references = (
            db.query(models.ShelfImageArtifactReference)
            .filter(
                models.ShelfImageArtifactReference.shelf_image_id == image_id,
                models.ShelfImageArtifactReference.store_id == store_id,
                models.ShelfImageArtifactReference.external_system == artifact.external_system,
            )
            .order_by(models.ShelfImageArtifactReference.id)
            .all()
        )
        inventory_integrity_verified = bool(
            snapshot is not None
            and verify_inventory_snapshot_record(
                snapshot=snapshot,
                expected_references=inventory_references,
                configured_keys_json=settings.artifact_inventory_hmac_keys_json,
            )
        )

        latest_event = (
            db.query(models.ShelfImageArtifactDispositionEvent)
            .filter(
                models.ShelfImageArtifactDispositionEvent.artifact_reference_id == artifact.id,
                models.ShelfImageArtifactDispositionEvent.shelf_image_id == image_id,
                models.ShelfImageArtifactDispositionEvent.store_id == store_id,
            )
            .order_by(models.ShelfImageArtifactDispositionEvent.sequence_number.desc())
            .with_for_update()
            .populate_existing()
            .first()
        )

        inventory_entry = None
        if snapshot is not None:
            inventory_entry = next(
                (
                    entry for entry in (snapshot.inventory_manifest or [])
                    if entry.get("artifact_type") == artifact.artifact_type
                    and entry.get("external_reference") == artifact.external_reference
                ),
                None,
            )

        decision = evaluate_artifact_access(
            artifact_reference_id=artifact.id,
            expected_artifact_type=artifact.artifact_type,
            expected_external_reference=artifact.external_reference,
            expected_sha256=artifact.sha256,
            source_retention_status=image.retention_status,
            source_legal_hold=image.legal_hold,
            integration_status=integration.status if integration is not None else "MISSING",
            inventory_complete=bool(snapshot and snapshot.inventory_complete),
            inventory_integrity_verified=inventory_integrity_verified,
            inventory_generated_at=snapshot.generated_at if snapshot is not None else None,
            inventory_verified_at=snapshot.verified_at if snapshot is not None else None,
            inventory_max_age_seconds=settings.artifact_inventory_max_age_minutes * 60,
            inventory_entry=inventory_entry,
            latest_disposition_event=latest_event.event_type if latest_event is not None else None,
            latest_disposition_at=latest_event.created_at if latest_event is not None else None,
            now=now or models.utc_now(),
        )
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
