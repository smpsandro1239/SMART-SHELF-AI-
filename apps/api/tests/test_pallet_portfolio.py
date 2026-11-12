import pytest

from app.pallet_portfolio import (
    PalletPortfolioInputError,
    build_pallet_portfolio_plan,
)


def candidate(pallet_id=1, **overrides):
    row = {
        "store_id": 1,
        "product_id": 42,
        "pallet_id": pallet_id,
        "residual_base_units": 300,
        "pallet_capacity_base_units": 720,
        "threshold_ratio": 0.5,
        "traffic_level": "HIGH",
        "replacement_pallet_available": True,
        "backroom_capacity_available": True,
        "forecast_consumption_until_low_traffic": 100,
        "conventional_minutes": 24,
        "swap_minutes": 4,
        "transport_minutes": 3,
        "rebuild_minutes": 5,
    }
    row.update(overrides)
    return row


def test_stockout_risk_precedes_economical_swap():
    result = build_pallet_portfolio_plan([
        candidate(1, forecast_consumption_until_low_traffic=400),
        candidate(2),
    ])
    assert [item["pallet_id"] for item in result.recommendations] == [1, 2]
    assert result.recommendations[0]["action"] == "INTERIM_REPLENISHMENT"


def test_swap_is_recommended_only_when_all_operational_gates_pass():
    result = build_pallet_portfolio_plan([candidate()])
    item = result.recommendations[0]
    assert item["action"] == "SWAP_PALLET"
    assert item["estimated_minutes_saved"] == 12
    assert item["automatic_stock_movement_allowed"] is False


@pytest.mark.parametrize("override, expected", [
    ({"traffic_level": "LOW"}, "REPLENISH_CURRENT"),
    ({"replacement_pallet_available": False}, "PREPARE_REPLACEMENT"),
    ({"backroom_capacity_available": False}, "REVIEW_BACKROOM"),
    ({"conventional_minutes": 8}, "REPLENISH_CURRENT"),
    ({"traffic_level": "UNKNOWN"}, "REVIEW_DATA"),
])
def test_operational_gates_produce_conservative_actions(override, expected):
    result = build_pallet_portfolio_plan([candidate(**override)])
    assert result.recommendations[0]["action"] == expected


def test_invalid_candidate_is_excluded_not_silently_normalised():
    result = build_pallet_portfolio_plan([
        candidate(1, residual_base_units=float("nan")),
        candidate(2),
    ])
    assert result.considered == 1
    assert result.excluded == 1
    assert result.recommendations[0]["pallet_id"] == 2


def test_duplicate_pallet_id_excludes_second_candidate():
    result = build_pallet_portfolio_plan([candidate(1), candidate(1)])
    assert result.considered == 1
    assert result.excluded == 1


@pytest.mark.parametrize("limit", [0, 501, True, 1.5])
def test_invalid_limit_is_rejected(limit):
    with pytest.raises(PalletPortfolioInputError):
        build_pallet_portfolio_plan([], limit=limit)


def test_plan_is_deterministic_and_read_only():
    source = [candidate(3), candidate(2)]
    result = build_pallet_portfolio_plan(source)
    assert [item["pallet_id"] for item in result.recommendations] == [2, 3]
    assert source[0]["pallet_id"] == 3
    assert result.automatic_stock_movement_allowed is False


def test_exactly_half_a_pallet_is_eligible_for_portfolio_swap():
    result = build_pallet_portfolio_plan([
        candidate(residual_base_units=360, forecast_consumption_until_low_traffic=120)
    ])
    item = result.recommendations[0]
    assert item["residual_ratio"] == 0.5
    assert item["action"] == "SWAP_PALLET"


def test_more_than_half_a_pallet_remaining_is_not_swapped():
    result = build_pallet_portfolio_plan([
        candidate(residual_base_units=361, forecast_consumption_until_low_traffic=120)
    ])
    item = result.recommendations[0]
    assert item["action"] == "REPLENISH_CURRENT"
    assert item["reason_code"] == "RESIDUAL_ABOVE_THRESHOLD"


@pytest.mark.parametrize("override", [
    {"threshold_ratio": 1.01},
    {"threshold_ratio": -0.01},
    {"residual_base_units": True},
    {"pallet_capacity_base_units": float("inf")},
])
def test_portfolio_rejects_invalid_threshold_and_quantity_values(override):
    result = build_pallet_portfolio_plan([candidate(**override)])
    assert result.considered == 0
    assert result.excluded == 1


def test_partial_pallet_is_never_treated_as_ready_replacement_by_planner():
    # Readiness is an explicit upstream boolean: a PARTIAL pallet must be
    # mapped to replacement_pallet_available=False by the API candidate builder.
    result = build_pallet_portfolio_plan([
        candidate(replacement_pallet_available=False)
    ])
    item = result.recommendations[0]
    assert item["action"] == "PREPARE_REPLACEMENT"
    assert item["automatic_stock_movement_allowed"] is False
