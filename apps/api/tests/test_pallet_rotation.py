import pytest

from app.pallet_rotation import PalletRotationInputError, evaluate_pallet_rotation


def inputs(**overrides):
    values = {
        "product_eligible": True,
        "residual_base_units": 300,
        "pallet_capacity_base_units": 720,
        "threshold_ratio": 0.5,
        "traffic_level": "HIGH",
        "replacement_pallet_available": True,
        "backroom_capacity_available": True,
        "conventional_replenishment_minutes": 24,
        "pallet_swap_minutes": 4,
        "transport_minutes": 3,
        "pallet_rebuild_minutes": 5,
        "labour_cost_per_hour": 12,
        "forecast_consumption_until_low_traffic": 180,
    }
    values.update(overrides)
    return values


def test_swap_is_recommended_when_operational_and_economic_conditions_pass():
    result = evaluate_pallet_rotation(**inputs())
    assert result.recommendation == "SWAP_PALLET"
    assert result.conventional_cost == pytest.approx(4.8)
    assert result.swap_cost == pytest.approx(2.4)
    assert result.estimated_minutes_saved == pytest.approx(12)
    assert result.automatic_stock_movement_allowed is False


def test_residual_above_threshold_keeps_current_pallet():
    result = evaluate_pallet_rotation(**inputs(residual_base_units=500))
    assert result.recommendation == "REPLENISH_CURRENT"


@pytest.mark.parametrize("traffic", ["LOW", "UNKNOWN"])
def test_traffic_window_controls_decision(traffic):
    result = evaluate_pallet_rotation(**inputs(traffic_level=traffic))
    assert result.recommendation == ("REPLENISH_CURRENT" if traffic == "LOW" else "INSUFFICIENT_DATA")


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"replacement_pallet_available": False}, "NO_READY_REPLACEMENT"),
        ({"backroom_capacity_available": False}, "NO_SAFE_BACKROOM_CAPACITY"),
    ],
)
def test_missing_operational_resource_prevents_swap(override, reason):
    result = evaluate_pallet_rotation(**inputs(**override))
    assert result.recommendation == "REPLENISH_CURRENT"
    assert result.reason_code == reason


def test_residual_must_cover_demand_until_low_traffic():
    result = evaluate_pallet_rotation(**inputs(forecast_consumption_until_low_traffic=350))
    assert result.recommendation == "REPLENISH_CURRENT"
    assert result.reason_code == "INTERIM_REPLENISHMENT_REQUIRED"


def test_more_expensive_swap_is_rejected():
    result = evaluate_pallet_rotation(**inputs(
        conventional_replenishment_minutes=10,
        pallet_swap_minutes=8,
        transport_minutes=5,
        pallet_rebuild_minutes=8,
    ))
    assert result.recommendation == "NOT_ECONOMICAL"


def test_ineligible_product_is_rejected():
    assert evaluate_pallet_rotation(**inputs(product_eligible=False)).recommendation == "NOT_ELIGIBLE"


def test_missing_cost_input_returns_insufficient_data():
    result = evaluate_pallet_rotation(**inputs(transport_minutes=None))
    assert result.recommendation == "INSUFFICIENT_DATA"
    assert result.inputs_complete is False


@pytest.mark.parametrize("override", [
    {"residual_base_units": -1},
    {"pallet_capacity_base_units": 0},
    {"residual_base_units": 800},
    {"threshold_ratio": 1.1},
    {"traffic_level": "BUSY"},
    {"labour_cost_per_hour": float("nan")},
])
def test_invalid_inputs_raise(override):
    with pytest.raises(PalletRotationInputError):
        evaluate_pallet_rotation(**inputs(**override))


def test_rotation_simulation_request_accepts_complete_operational_inputs():
    from app.schemas import PalletRotationSimulationRequest

    payload = PalletRotationSimulationRequest(
        store_id=1,
        pallet_id=15,
        traffic_level="HIGH",
        backroom_capacity_available=True,
        conventional_replenishment_minutes=24,
        pallet_swap_minutes=4,
        transport_minutes=3,
        pallet_rebuild_minutes=5,
        labour_cost_per_hour=12,
        forecast_consumption_until_low_traffic=180,
    )
    assert payload.pallet_id == 15
    assert payload.traffic_level == "HIGH"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_rotation_simulation_request_rejects_invalid_operational_values(value):
    from pydantic import ValidationError
    from app.schemas import PalletRotationSimulationRequest

    with pytest.raises(ValidationError):
        PalletRotationSimulationRequest(
            store_id=1,
            pallet_id=15,
            traffic_level="HIGH",
            backroom_capacity_available=True,
            conventional_replenishment_minutes=value,
            pallet_swap_minutes=4,
            transport_minutes=3,
            pallet_rebuild_minutes=5,
            labour_cost_per_hour=12,
            forecast_consumption_until_low_traffic=180,
        )
