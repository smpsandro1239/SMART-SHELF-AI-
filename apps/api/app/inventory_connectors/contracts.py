"""Provider-neutral contracts for read-only ERP/WMS inventory adapters.

Concrete vendor adapters must implement this contract. This module performs no
network calls and deliberately does not provide a simulated ERP/WMS provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from importlib import import_module
from typing import Literal, Protocol, runtime_checkable

InventorySource = Literal["ERP", "WMS"]


class InventoryAdapterError(RuntimeError):
    """Base exception for adapter loading and contract violations."""


class InventoryAdapterNotConfigured(InventoryAdapterError):
    """Raised when no real provider adapter has been configured."""


class InventoryAdapterContractError(InventoryAdapterError):
    """Raised when a provider does not satisfy the normalized contract."""


def _quantity(value: Decimal | int | float | str, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite non-negative decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a finite non-negative decimal") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be a finite non-negative decimal")
    if result != result.quantize(Decimal("0.001")) or result >= Decimal("1000000000"):
        raise ValueError(f"{field} must fit the inventory precision Numeric(12, 3)")
    return result


@dataclass(frozen=True, slots=True)
class NormalizedInventoryRecord:
    """One source-owned stock observation, normalized before API persistence."""

    external_product_id: str
    sku: str
    on_hand_quantity: Decimal
    reserved_quantity: Decimal
    captured_at: datetime
    external_reference: str

    def __post_init__(self) -> None:
        for field, maximum in (("external_product_id", 120), ("sku", 120), ("external_reference", 120)):
            value = getattr(self, field)
            normalized = value.strip() if isinstance(value, str) else ""
            if not normalized or len(normalized) > maximum:
                raise ValueError(f"{field} must contain between 1 and {maximum} characters")
            object.__setattr__(self, field, normalized)

        on_hand = _quantity(self.on_hand_quantity, "on_hand_quantity")
        reserved = _quantity(self.reserved_quantity, "reserved_quantity")
        if reserved > on_hand:
            raise ValueError("reserved_quantity cannot exceed on_hand_quantity")
        object.__setattr__(self, "on_hand_quantity", on_hand)
        object.__setattr__(self, "reserved_quantity", reserved)

        if not isinstance(self.captured_at, datetime) or self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be a timezone-aware datetime")


@dataclass(frozen=True, slots=True)
class InventorySyncBatch:
    """A complete or paginated response from one real ERP/WMS adapter call."""

    source: InventorySource
    provider: str
    external_run_id: str | None
    records: tuple[NormalizedInventoryRecord, ...]
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if self.source not in {"ERP", "WMS"}:
            raise ValueError("source must be ERP or WMS")
        provider = self.provider.strip() if isinstance(self.provider, str) else ""
        if not provider or len(provider) > 120:
            raise ValueError("provider must contain between 1 and 120 characters")
        object.__setattr__(self, "provider", provider)
        if self.external_run_id is not None:
            run_id = self.external_run_id.strip()
            if not run_id or len(run_id) > 200:
                raise ValueError("external_run_id must contain between 1 and 200 characters")
            object.__setattr__(self, "external_run_id", run_id)
        if not isinstance(self.records, tuple) or any(not isinstance(item, NormalizedInventoryRecord) for item in self.records):
            raise ValueError("records must be a tuple of NormalizedInventoryRecord")
        references = [item.external_reference for item in self.records]
        if len(references) != len(set(references)):
            raise ValueError("external_reference values must be unique within a batch")
        skus = [item.sku.casefold() for item in self.records]
        if len(skus) != len(set(skus)):
            raise ValueError("SKU values must be unique within a batch")
        if self.next_cursor is not None:
            cursor = self.next_cursor.strip()
            if not cursor or len(cursor) > 1000:
                raise ValueError("next_cursor must contain between 1 and 1000 characters")
            object.__setattr__(self, "next_cursor", cursor)


@runtime_checkable
class InventorySourceAdapter(Protocol):
    """Read-only adapter interface. Implementations must never mutate source stock."""

    source: InventorySource
    provider: str

    async def fetch_inventory(
        self,
        store_external_code: str,
        cursor: str | None = None,
    ) -> InventorySyncBatch:
        """Fetch one page of stock evidence for a single external store."""


def load_inventory_adapter(factory_path: str, expected_source: InventorySource) -> InventorySourceAdapter:
    """Load a trusted deployment-configured factory using 'module:callable'.

    Import paths are configuration, not user input. No default/mock adapter is
    supplied: an absent or invalid provider fails closed.
    """
    if not factory_path or ":" not in factory_path:
        raise InventoryAdapterNotConfigured(
            f"No real {expected_source} adapter factory is configured"
        )
    module_name, attribute_name = factory_path.split(":", 1)
    if not module_name.strip() or not attribute_name.strip():
        raise InventoryAdapterNotConfigured("Adapter factory must use 'module:callable' syntax")
    try:
        factory = getattr(import_module(module_name), attribute_name)
    except (ImportError, AttributeError) as exc:
        raise InventoryAdapterContractError("Configured inventory adapter factory cannot be loaded") from exc
    if not callable(factory):
        raise InventoryAdapterContractError("Configured inventory adapter factory is not callable")
    adapter = factory()
    if not isinstance(adapter, InventorySourceAdapter):
        raise InventoryAdapterContractError("Adapter does not implement the inventory source contract")
    if adapter.source != expected_source:
        raise InventoryAdapterContractError("Configured adapter source does not match the requested source")
    if not isinstance(adapter.provider, str) or not adapter.provider.strip():
        raise InventoryAdapterContractError("Adapter provider identity is missing")
    return adapter
