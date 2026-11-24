"""Read-only ERP/WMS adapter contracts.

Vendor implementations are deployment-specific and must be explicitly
configured. No mock connector is registered as a production integration.
"""
from .contracts import (
    InventoryAdapterContractError,
    InventoryAdapterError,
    InventoryAdapterNotConfigured,
    InventorySourceAdapter,
    InventorySyncBatch,
    NormalizedInventoryRecord,
    load_inventory_adapter,
)

__all__ = [
    "InventoryAdapterContractError",
    "InventoryAdapterError",
    "InventoryAdapterNotConfigured",
    "InventorySourceAdapter",
    "InventorySyncBatch",
    "NormalizedInventoryRecord",
    "load_inventory_adapter",
]
