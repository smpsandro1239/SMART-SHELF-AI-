import pytest

from app.pallet_rotation_forecast_bridge import enrich_pallet_candidates_with_hourly_profiles


def profile():
    return [
        {
            "hour_of_day": hour,
            "average_daily_units": 5,
            "sales_observed_days": 14,
            "average_customers": 100 if 9 <= hour <= 17 else 20,
            "traffic_observed_days": 14,
        }
        for hour in range(24)
    ]


def candidate(product_id=42, **overrides):
    row = {
        "store_id": 1,
        "product_id": product_id,
        "pallet_id": 100 + product_id,
        "residual_base_units": 200,
    }
    row.update(overrides)
    return row


def test_enriches_each_product_with_its_own_hourly_profile():
    result = enrich_pallet_candidates_with_hourly_profiles(
        [candidate()],
        {42: profile()},
        current_hour=8,
        duration_hours=2,
        minimum_observed_days=7,
    )
    row = result["candidates"][0]
    assert row["traffic_level"] == "LOW"
    assert row["recommended_window_start_hour"] == 18
    assert row["forecast_consumption_until_low_traffic"] == 60
    assert row["planning_reason"] == "LOWEST_OBSERVED_TRAFFIC_WINDOW"
    assert result["without_sufficient_profile"] == 0
    assert result["automatic_stock_movement_allowed"] is False


def test_missing_product_profile_remains_unknown_not_zero():
    result = enrich_pallet_candidates_with_hourly_profiles(
        [candidate()],
        {},
        current_hour=8,
    )
    row = result["candidates"][0]
    assert row["traffic_level"] == "UNKNOWN"
    assert row["forecast_consumption_until_low_traffic"] is None
    assert row["planning_reason"] == "HOURLY_PROFILE_MISSING"
    assert result["without_sufficient_profile"] == 1


def test_incomplete_profile_is_not_filled_with_zero():
    rows = profile()
    rows[10]["average_customers"] = None
    rows[10]["traffic_observed_days"] = 0
    result = enrich_pallet_candidates_with_hourly_profiles(
        [candidate()],
        {42: rows},
        current_hour=8,
    )
    row = result["candidates"][0]
    assert row["traffic_level"] == "UNKNOWN"
    assert row["forecast_consumption_until_low_traffic"] is None
    assert row["planning_reason"] == "HOURLY_PROFILE_INCOMPLETE"


def test_invalid_product_id_is_excluded_from_automatic_enrichment():
    result = enrich_pallet_candidates_with_hourly_profiles(
        [candidate(product_id=True)],
        {},
        current_hour=8,
    )
    row = result["candidates"][0]
    assert row["traffic_level"] == "UNKNOWN"
    assert row["planning_reason"] == "INVALID_PRODUCT_ID"
    assert result["without_sufficient_profile"] == 1


def test_multiple_products_use_separate_profiles():
    low_demand = profile()
    high_demand = profile()
    for row in high_demand:
        row["average_daily_units"] = 12
    result = enrich_pallet_candidates_with_hourly_profiles(
        [candidate(42), candidate(43)],
        {42: low_demand, 43: high_demand},
        current_hour=8,
    )
    rows = {row["product_id"]: row for row in result["candidates"]}
    assert rows[42]["forecast_consumption_until_low_traffic"] == 55
    assert rows[43]["forecast_consumption_until_low_traffic"] == 132


def test_current_traffic_is_high_when_current_hour_exceeds_daily_hourly_average():
    result = enrich_pallet_candidates_with_hourly_profiles(
        [candidate()],
        {42: profile()},
        current_hour=12,
    )
    row = result["candidates"][0]
    assert row["traffic_level"] == "HIGH"
    assert row["current_hour_average_customers"] == 100


def test_profile_row_order_does_not_change_current_hour_classification():
    rows = list(reversed(profile()))
    result = enrich_pallet_candidates_with_hourly_profiles(
        [candidate()],
        {42: rows},
        current_hour=12,
    )
    assert result["candidates"][0]["traffic_level"] == "HIGH"
    assert result["candidates"][0]["current_hour_average_customers"] == 100


def test_incomplete_profile_returns_unknown_without_crashing_on_missing_current_hour_value():
    rows = profile()
    rows[8]["average_customers"] = None
    rows[8]["traffic_observed_days"] = 0
    result = enrich_pallet_candidates_with_hourly_profiles(
        [candidate()],
        {42: rows},
        current_hour=8,
        minimum_observed_days=7,
    )
    row = result["candidates"][0]
    assert row["traffic_level"] == "UNKNOWN"
    assert row["forecast_consumption_until_low_traffic"] is None
    assert row["planning_recommendation"] == "INSUFFICIENT_DATA"
    assert row["planning_reason"] == "HOURLY_PROFILE_INCOMPLETE"


def test_insufficient_residual_is_reported_as_interim_replenishment_not_missing_data():
    result = enrich_pallet_candidates_with_hourly_profiles(
        [candidate(residual_base_units=1)],
        {42: profile()},
        current_hour=8,
        duration_hours=2,
        minimum_observed_days=7,
    )
    row = result["candidates"][0]
    assert row["planning_recommendation"] == "REPLENISH_CURRENT"
    assert row["planning_reason"] == "RESIDUAL_CANNOT_REACH_WINDOW"
    assert row["forecast_consumption_until_low_traffic"] is None
    assert row["traffic_level"] in {"LOW", "HIGH"}
