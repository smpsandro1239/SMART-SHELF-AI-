"""Focused tests for ERP/WMS ingestion orchestration safeguards."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.inventory_connectors.contracts import NormalizedInventoryRecord
from app.inventory_connectors.orchestrator import _fetch_page, _same_snapshot


def _record():
    return NormalizedInventoryRecord(
        external_product_id="ext-1", sku="SKU-1",
        on_hand_quantity=Decimal("10.000"), reserved_quantity=Decimal("2.000"),
        captured_at=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
        external_reference="row-1",
    )


def test_idempotent_snapshot_comparison_normalizes_sqlite_naive_timestamps():
    existing = SimpleNamespace(
        on_hand_quantity=Decimal("10.000"),
        reserved_quantity=Decimal("2.000"),
        captured_at=datetime(2026, 11, 24, 12, 0),
    )
    assert _same_snapshot(existing, _record())
    existing.on_hand_quantity = Decimal("11.000")
    assert not _same_snapshot(existing, _record())


@pytest.mark.asyncio
async def test_provider_page_fetch_uses_bounded_retry_before_success():
    class FlakyAdapter:
        calls = 0

        async def fetch_inventory(self, store_code, cursor=None):
            self.calls += 1
            if self.calls < 3:
                raise TimeoutError("transient provider timeout")
            return "page"

    adapter = FlakyAdapter()
    result = await _fetch_page(adapter, "STORE-1", None, 2)
    assert result == "page"
    assert adapter.calls == 3


@pytest.mark.asyncio
async def test_provider_page_fetch_stops_after_retry_limit():
    class BrokenAdapter:
        calls = 0

        async def fetch_inventory(self, store_code, cursor=None):
            self.calls += 1
            raise TimeoutError("provider unavailable")

    adapter = BrokenAdapter()
    with pytest.raises(RuntimeError, match="bounded retries"):
        await _fetch_page(adapter, "STORE-1", None, 2)
    assert adapter.calls == 3
