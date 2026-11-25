from datetime import datetime, timezone
from decimal import Decimal
from types import ModuleType
import sys

import pytest

from app.inventory_connectors.contracts import (
    InventoryAdapterContractError,
    InventoryAdapterNotConfigured,
    InventorySyncBatch,
    NormalizedInventoryRecord,
    load_inventory_adapter,
)


def record(**overrides):
    values = {
        "external_product_id": "erp-product-1",
        "sku": "SKU-001",
        "on_hand_quantity": Decimal("12.500"),
        "reserved_quantity": Decimal("2.000"),
        "captured_at": datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
        "external_reference": "stock-row-001",
        "location_code": "BACKROOM-A",
        "availability_status": "AVAILABLE",
    }
    values.update(overrides)
    return NormalizedInventoryRecord(**values)


def test_normalized_record_preserves_decimal_quantities_and_timezone():
    item = record()
    assert item.on_hand_quantity == Decimal("12.500")
    assert item.reserved_quantity == Decimal("2.000")
    assert item.sku == "SKU-001"


@pytest.mark.parametrize("changes", [
    {"on_hand_quantity": -1},
    {"reserved_quantity": 13},
    {"on_hand_quantity": "NaN"},
    {"on_hand_quantity": "1.0001"},
    {"on_hand_quantity": 1_000_000_000},
    {"captured_at": datetime(2026, 11, 24, 12, 0)},
    {"sku": "   "},
])
def test_normalized_record_rejects_invalid_source_evidence(changes):
    with pytest.raises(ValueError):
        record(**changes)


def test_batch_rejects_duplicate_source_references_and_skus():
    with pytest.raises(ValueError, match="external_reference"):
        InventorySyncBatch("ERP", "ERP vendor", None, (record(), record(sku="SKU-002")))
    with pytest.raises(ValueError, match="SKU"):
        InventorySyncBatch("WMS", "WMS vendor", None, (record(), record(external_reference="row-002")))


def test_batch_accepts_pagination_metadata():
    batch = InventorySyncBatch("WMS", "WMS vendor", "run-10", (record(),), "next-page")
    assert batch.next_cursor == "next-page"
    assert len(batch.records) == 1


def test_wms_batch_requires_location_and_explicit_availability():
    with pytest.raises(ValueError, match="physical location and availability"):
        InventorySyncBatch(
            "WMS", "WMS vendor", None,
            (record(location_code=None, availability_status="UNKNOWN"),),
        )


def test_erp_batch_does_not_claim_backroom_location_authority():
    batch = InventorySyncBatch(
        "ERP", "ERP vendor", None,
        (record(location_code=None, availability_status="UNKNOWN"),),
    )
    assert batch.records[0].location_code is None


def test_adapter_loader_fails_closed_when_not_configured():
    with pytest.raises(InventoryAdapterNotConfigured):
        load_inventory_adapter("", "ERP")


def test_adapter_loader_rejects_provider_source_mismatch(monkeypatch):
    module = ModuleType("test_inventory_adapter_module")

    class WrongSourceAdapter:
        source = "WMS"
        provider = "WMS vendor"

        async def fetch_inventory(self, store_external_code, cursor=None):
            raise NotImplementedError

    module.create_adapter = WrongSourceAdapter
    monkeypatch.setitem(sys.modules, module.__name__, module)
    with pytest.raises(InventoryAdapterContractError, match="does not match"):
        load_inventory_adapter("test_inventory_adapter_module:create_adapter", "ERP")


def test_adapter_loader_accepts_contract_implementation(monkeypatch):
    module = ModuleType("test_inventory_adapter_valid_module")

    class ERPAdapter:
        source = "ERP"
        provider = "ERP vendor"

        async def fetch_inventory(self, store_external_code, cursor=None):
            return InventorySyncBatch("ERP", self.provider, None, (record(),))

    module.create_adapter = ERPAdapter
    monkeypatch.setitem(sys.modules, module.__name__, module)
    adapter = load_inventory_adapter("test_inventory_adapter_valid_module:create_adapter", "ERP")
    assert adapter.provider == "ERP vendor"
