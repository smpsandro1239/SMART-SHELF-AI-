from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.replenishment_risk_bridge import enrich_replenishment_with_stockout_risk


def _recommendation(**overrides):
    item = {
        "store_id": 1,
        "shelf_id": 10,
        "product_id": 42,
        "recommendation_status": "NEEDS_REPLENISHMENT",
        "suggested_quantity": 5,
        "inventory_available_quantity": 20,
        "inventory_captured_at": datetime(2026, 11, 12, 10, tzinfo=timezone.utc),
    }
    item.update(overrides)
    return item


def _history(end_day, days=28, quantity=10):
    return [
        SimpleNamespace(
            product_id=42,
            sales_date=end_day - timedelta(days=offset),
            quantity=quantity,
        )
        for offset in range(days)
    ]


def test_bridge_calculates_critical_risk_from_complete_history_and_fresh_stock():
    today = date(2026, 11, 12)
    now = datetime(2026, 11, 12, 11, tzinfo=timezone.utc)
    enriched = enrich_replenishment_with_stockout_risk(
        [_recommendation()],
        _history(today),
        through_date=today,
        now=now,
        days=28,
        lead_time_days=3,
    )

    item = enriched[0]
    assert item["stockout_risk_level"] == "CRITICAL"
    assert item["stockout_risk_basis"] == "DAILY_SALES_AND_FRESH_INVENTORY"
    assert item["stockout_missing_sales_days"] == 0
    assert item["stockout_average_daily_demand"] == 10
    assert item["stockout_projected_stock_at_receipt"] == -10


def test_bridge_keeps_risk_unknown_when_one_sales_day_is_missing():
    today = date(2026, 11, 12)
    history = _history(today)
    history.pop(4)
    enriched = enrich_replenishment_with_stockout_risk(
        [_recommendation()],
        history,
        through_date=today,
        now=datetime(2026, 11, 12, 11, tzinfo=timezone.utc),
    )

    assert enriched[0]["stockout_risk_level"] == "UNKNOWN"
    assert enriched[0]["stockout_missing_sales_days"] == 1
    assert enriched[0]["stockout_risk_basis"] == "INSUFFICIENT_EVIDENCE"


def test_bridge_keeps_risk_unknown_when_inventory_snapshot_is_stale():
    today = date(2026, 11, 12)
    enriched = enrich_replenishment_with_stockout_risk(
        [_recommendation(inventory_captured_at=datetime(2026, 11, 12, 5, tzinfo=timezone.utc))],
        _history(today),
        through_date=today,
        now=datetime(2026, 11, 12, 11, tzinfo=timezone.utc),
        max_inventory_age_minutes=240,
    )

    assert enriched[0]["stockout_risk_level"] == "UNKNOWN"
    assert enriched[0]["stockout_risk_basis"] == "STALE_INVENTORY"


def test_bridge_aggregates_multiple_records_for_same_day():
    today = date(2026, 11, 12)
    history = _history(today)
    history[0].quantity = 4
    history.append(SimpleNamespace(
        product_id=42, sales_date=today, quantity=6
    ))
    enriched = enrich_replenishment_with_stockout_risk(
        [_recommendation(inventory_available_quantity=1000)],
        history,
        through_date=today,
        now=datetime(2026, 11, 12, 11, tzinfo=timezone.utc),
    )

    assert enriched[0]["stockout_risk_level"] == "LOW"
    assert enriched[0]["stockout_missing_sales_days"] == 0


def test_bridge_does_not_mutate_input_recommendation():
    today = date(2026, 11, 12)
    source = _recommendation()
    original = dict(source)
    enrich_replenishment_with_stockout_risk(
        [source], _history(today), through_date=today,
        now=datetime(2026, 11, 12, 11, tzinfo=timezone.utc),
    )
    assert source == original


def test_bridge_rejects_boolean_sales_quantity():
    today = date(2026, 11, 12)
    history = _history(today)
    history[0].quantity = True
    with pytest.raises(ValueError, match="cannot be boolean"):
        enrich_replenishment_with_stockout_risk(
            [_recommendation()], history, through_date=today,
            now=datetime(2026, 11, 12, 11, tzinfo=timezone.utc),
        )


def test_bridge_keeps_risk_unknown_when_inventory_snapshot_is_in_the_future():
    today = date(2026, 11, 12)
    enriched = enrich_replenishment_with_stockout_risk(
        [_recommendation(inventory_captured_at=datetime(2026, 11, 12, 12, tzinfo=timezone.utc))],
        _history(today),
        through_date=today,
        now=datetime(2026, 11, 12, 11, tzinfo=timezone.utc),
    )

    item = enriched[0]
    assert item["stockout_risk_level"] == "UNKNOWN"
    assert item["stockout_risk_basis"] == "FUTURE_INVENTORY"
    assert "data futura" in item["stockout_explanation"]


def test_bridge_rejects_boolean_inventory_quantity_without_coercing_it():
    today = date(2026, 11, 12)
    with pytest.raises(ValueError, match="cannot be boolean"):
        enrich_replenishment_with_stockout_risk(
            [_recommendation(inventory_available_quantity=True)],
            _history(today),
            through_date=today,
            now=datetime(2026, 11, 12, 11, tzinfo=timezone.utc),
        )


def test_bridge_rejects_datetime_as_through_date():
    today = date(2026, 11, 12)
    with pytest.raises(ValueError, match="calendar date"):
        enrich_replenishment_with_stockout_risk(
            [_recommendation()],
            _history(today),
            through_date=datetime(2026, 11, 12, 0, tzinfo=timezone.utc),
            now=datetime(2026, 11, 12, 11, tzinfo=timezone.utc),
        )
