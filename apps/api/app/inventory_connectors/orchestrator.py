"""Read-only ERP/WMS synchronization orchestration for trusted workers.

This service is deliberately not exposed as an HTTP endpoint. A worker must
resolve the adapter and secrets from trusted deployment configuration, then
supply a store-scoped service actor. Each page is committed atomically; retries
are bounded and snapshot identity is protected by the database uniqueness key.
"""
from __future__ import annotations

import asyncio
from datetime import timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.inventory_connectors.contracts import (
    InventoryAdapterContractError,
    InventorySourceAdapter,
    InventorySyncBatch,
)

MAX_PAGES_PER_RUN = 1000
MAX_RETRIES_PER_PAGE = 3
DEFAULT_PAGE_TIMEOUT_SECONDS = 30


class InventorySyncOrchestrationError(RuntimeError):
    """A synchronization run cannot safely continue."""


def _utc(value):
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _same_snapshot(existing: models.InventorySnapshot, item: Any) -> bool:
    return (
        Decimal(str(existing.on_hand_quantity)) == item.on_hand_quantity
        and Decimal(str(existing.reserved_quantity)) == item.reserved_quantity
        and existing.location_code == item.location_code
        and existing.availability_status == item.availability_status
        and _utc(existing.captured_at) == _utc(item.captured_at)
    )


async def _fetch_page(adapter, store_code: str, cursor: str | None, timeout: int):
    last_error = None
    for attempt in range(MAX_RETRIES_PER_PAGE):
        try:
            return await asyncio.wait_for(
                adapter.fetch_inventory(store_code, cursor=cursor),
                timeout=timeout,
            )
        except (InventoryAdapterContractError, asyncio.CancelledError):
            raise
        except Exception as exc:  # provider/network exception; never expose its text
            last_error = exc
            if attempt + 1 < MAX_RETRIES_PER_PAGE:
                await asyncio.sleep(0.25 * (2 ** attempt))
    raise InventorySyncOrchestrationError("Provider page fetch failed after bounded retries") from last_error


def _complete_sync(
    db: Session,
    sync: models.InventorySourceSync,
    actor_user_id: int,
    *,
    status: str,
    received: int,
    processed: int,
    error_code: str | None = None,
    error_message: str | None = None,
    external_run_id: str | None = None,
    lease_guard: Callable[[Session], Any] | None = None,
) -> None:
    if lease_guard is not None:
        lease_guard(db)
    now = models.utc_now()
    sync.status = status
    if external_run_id is not None:
        sync.external_run_id = external_run_id
    sync.finished_at = now
    sync.received_records = received
    sync.processed_records = processed
    sync.error_code = error_code
    sync.error_message = error_message
    db.add(models.InventorySourceSyncEvent(
        sync_id=sync.id,
        event_type="COMPLETED",
        actor_user_id=actor_user_id,
        details={
            "status": status,
            "received_records": received,
            "processed_records": processed,
            "error_code": error_code,
            "error_message": error_message,
        },
        created_at=now,
    ))
    db.commit()


async def run_inventory_source_sync(
    db: Session,
    *,
    store_id: int,
    source: str,
    adapter: InventorySourceAdapter,
    actor_user_id: int,
    page_timeout_seconds: int = DEFAULT_PAGE_TIMEOUT_SECONDS,
    lease_guard: Callable[[Session], Any] | None = None,
) -> dict[str, int | str]:
    """Fetch and persist one provider's complete paginated inventory snapshot.

    actor_user_id must identify a dedicated service user or the authorized
    initiating supervisor. The function never changes products, ERP/WMS stock,
    inventory movements, reconciliations, or review decisions.
    """
    if source not in {"ERP", "WMS"} or adapter.source != source:
        raise InventorySyncOrchestrationError("Adapter source does not match requested source")
    if page_timeout_seconds < 1 or page_timeout_seconds > 300:
        raise ValueError("page_timeout_seconds must be between 1 and 300")
    store = db.get(models.Store, store_id)
    if store is None:
        raise InventorySyncOrchestrationError("Store does not exist")
    actor = db.get(models.User, actor_user_id)
    if actor is None:
        raise InventorySyncOrchestrationError("Synchronization actor does not exist")

    integration = (
        db.query(models.StoreExternalIntegration)
        .filter_by(store_id=store_id, external_system=source, status="ACTIVE")
        .with_for_update()
        .first()
    )
    if integration is None or integration.provider != adapter.provider:
        raise InventorySyncOrchestrationError("No active store integration matches this provider")

    lease_job = lease_guard(db) if lease_guard is not None else None
    now = models.utc_now()
    sync = models.InventorySourceSync(
        store_id=store_id,
        source=source,
        provider=adapter.provider,
        status="STARTED",
        started_at=now,
        created_by_user_id=actor_user_id,
        created_at=now,
    )
    db.add(sync)
    db.flush()
    if lease_job is not None:
        lease_job.latest_sync_id = sync.id
    db.add(models.InventorySourceSyncEvent(
        sync_id=sync.id,
        event_type="STARTED",
        actor_user_id=actor_user_id,
        details={"source": source, "provider": adapter.provider, "execution": "worker"},
        created_at=now,
    ))
    db.commit()
    db.refresh(sync)

    received = 0
    processed = 0
    cursor = None
    seen_cursors: set[str] = set()
    external_run_id = None

    try:
        for page_number in range(1, MAX_PAGES_PER_RUN + 1):
            batch = await _fetch_page(adapter, store.code, cursor, page_timeout_seconds)
            if not isinstance(batch, InventorySyncBatch):
                raise InventoryAdapterContractError("Adapter returned an invalid batch")
            if batch.source != source or batch.provider != adapter.provider:
                raise InventoryAdapterContractError("Batch identity differs from configured adapter")
            if external_run_id is None:
                external_run_id = batch.external_run_id
            elif batch.external_run_id != external_run_id:
                raise InventoryAdapterContractError("Provider changed external run identity between pages")

            received += len(batch.records)
            page_processed = 0
            for item in batch.records:
                mapping = (
                    db.query(models.InventoryExternalProductMapping)
                    .filter_by(
                        store_id=store_id,
                        source=source,
                        external_product_id=item.external_product_id,
                        external_sku=item.sku,
                        active=True,
                    )
                    .with_for_update()
                    .first()
                )
                if mapping is None:
                    raise InventorySyncOrchestrationError(
                        "A source product has no active, exact store-scoped SKU mapping"
                    )
                product = db.query(models.Product).filter_by(id=mapping.product_id, is_active=True).first()
                if product is None:
                    raise InventorySyncOrchestrationError("Mapped internal product is missing or inactive")
                existing = (
                    db.query(models.InventorySnapshot)
                    .filter_by(
                        store_id=store_id,
                        product_id=mapping.product_id,
                        source=source,
                        external_reference=item.external_reference,
                    )
                    .with_for_update()
                    .first()
                )
                if existing is not None:
                    if not _same_snapshot(existing, item):
                        raise InventorySyncOrchestrationError(
                            "An external reference was replayed with different snapshot content"
                        )
                    page_processed += 1
                    continue
                db.add(models.InventorySnapshot(
                    store_id=store_id,
                    product_id=mapping.product_id,
                    on_hand_quantity=item.on_hand_quantity,
                    reserved_quantity=item.reserved_quantity,
                    source=source,
                    external_reference=item.external_reference,
                    location_code=item.location_code,
                    availability_status=item.availability_status,
                    captured_at=item.captured_at,
                    created_at=models.utc_now(),
                ))
                page_processed += 1
            try:
                if lease_guard is not None:
                    lease_guard(db)
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise InventorySyncOrchestrationError(
                    "Concurrent ingestion created a conflicting source reference"
                ) from exc
            processed += page_processed

            if batch.next_cursor is None:
                _complete_sync(
                    db, sync, actor_user_id, status="SUCCESS",
                    received=received, processed=processed,
                    external_run_id=external_run_id, lease_guard=lease_guard,
                )
                return {"sync_id": sync.id, "status": "SUCCESS", "received_records": received, "processed_records": processed}
            if batch.next_cursor in seen_cursors or batch.next_cursor == cursor:
                raise InventoryAdapterContractError("Provider pagination cursor repeated")
            seen_cursors.add(batch.next_cursor)
            cursor = batch.next_cursor

        raise InventorySyncOrchestrationError("Provider exceeded the maximum page count")
    except asyncio.CancelledError:
        db.rollback()
        _complete_sync(
            db, sync, actor_user_id,
            status="PARTIAL" if processed else "FAILED",
            received=received, processed=processed,
            error_code="SYNC_CANCELLED",
            error_message="Synchronization was cancelled; committed pages remain available as evidence.",
            external_run_id=external_run_id, lease_guard=lease_guard,
        )
        raise
    except Exception as exc:
        db.rollback()
        status = "PARTIAL" if processed else "FAILED"
        code = "SYNC_PARTIAL" if processed else "SYNC_FAILED"
        # Do not persist provider exception text: it may contain URLs or secrets.
        message = "Synchronization stopped after a validation, provider, or persistence error."
        _complete_sync(
            db, sync, actor_user_id, status=status,
            received=received, processed=processed,
            error_code=code, error_message=message,
            external_run_id=external_run_id, lease_guard=lease_guard,
        )
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise InventorySyncOrchestrationError(message) from exc
