import pytest

from app.pallet_rotation_windows import recommend_low_traffic_window


def profile():
    rows = []
    for hour in range(24):
        rows.append({
            "hour_of_day": hour,
            "average_daily_units": 5,
            "sales_observed_days": 14,
            "average_customers": 100 if 9 <= hour <= 17 else 20,
            "traffic_observed_days": 14,
        })
    return rows


def test_selects_low_traffic_window_with_sufficient_residual_cover():
    result = recommend_low_traffic_window(
        profile(), current_hour=8, duration_hours=2,
        residual_base_units=200, minimum_observed_days=7,
    )
    assert result.recommendation == "WAIT_FOR_LOW_TRAFFIC"
    assert result.start_hour == 18
    assert result.projected_consumption_through_window == 60
    assert result.automatic_stock_movement_allowed is False


def test_requires_interim_replenishment_when_residual_cannot_reach_any_window():
    result = recommend_low_traffic_window(
        profile(), current_hour=8, duration_hours=2,
        residual_base_units=1, minimum_observed_days=7,
    )
    assert result.recommendation == "REPLENISH_CURRENT"
    assert result.reason_code == "RESIDUAL_CANNOT_REACH_WINDOW"


def test_missing_observations_are_not_treated_as_zero():
    rows = profile()
    rows[10]["average_customers"] = None
    rows[10]["traffic_observed_days"] = 0
    result = recommend_low_traffic_window(
        rows, current_hour=8, duration_hours=2,
        residual_base_units=200, minimum_observed_days=7,
    )
    assert result.recommendation == "INSUFFICIENT_DATA"


@pytest.mark.parametrize(
    "overrides",
    [
        {"current_hour": 24},
        {"duration_hours": 0},
        {"minimum_observed_days": 0},
        {"residual_base_units": -1},
    ],
)
def test_rejects_invalid_window_inputs(overrides):
    values = {
        "current_hour": 8, "duration_hours": 2,
        "residual_base_units": 200, "minimum_observed_days": 7,
    }
    values.update(overrides)
    with pytest.raises(ValueError):
        recommend_low_traffic_window(profile(), **values)


def test_requires_exactly_24_unique_hour_rows():
    with pytest.raises(ValueError):
        recommend_low_traffic_window(profile()[:-1], current_hour=8,
            duration_hours=2, residual_base_units=200)


def test_any_unobserved_hour_prevents_claiming_global_lowest_traffic():
    rows = profile()
    rows[3]["average_customers"] = None
    rows[3]["traffic_observed_days"] = 0
    result = recommend_low_traffic_window(
        rows, current_hour=8, duration_hours=1,
        residual_base_units=200, minimum_observed_days=7,
    )
    assert result.recommendation == "INSUFFICIENT_DATA"
    assert result.reason_code == "HOURLY_PROFILE_INCOMPLETE"


@pytest.mark.parametrize("field,value", [
    ("average_daily_units", -0.1),
    ("average_daily_units", float("nan")),
    ("average_customers", -1),
    ("average_customers", float("inf")),
])
def test_rejects_invalid_hourly_observation_values(field, value):
    rows = profile()
    rows[4][field] = value
    result = recommend_low_traffic_window(
        rows, current_hour=8, duration_hours=1,
        residual_base_units=200, minimum_observed_days=7,
    )
    assert result.recommendation == "INSUFFICIENT_DATA"
    assert result.reason_code == "HOURLY_PROFILE_INCOMPLETE"


def test_insufficient_coverage_prevents_global_window_recommendation():
    rows = profile()
    rows[2]["sales_observed_days"] = 2
    result = recommend_low_traffic_window(
        rows, current_hour=8, duration_hours=1,
        residual_base_units=200, minimum_observed_days=7,
    )
    assert result.recommendation == "INSUFFICIENT_DATA"


@pytest.mark.parametrize("field,value", [
    ("sales_observed_days", True),
    ("traffic_observed_days", False),
    ("sales_observed_days", 7.5),
    ("traffic_observed_days", "14"),
])
def test_rejects_non_integer_or_boolean_coverage_counts(field, value):
    rows = profile()
    rows[0][field] = value
    with pytest.raises(ValueError, match="coverage counts must be integers"):
        recommend_low_traffic_window(
            rows, current_hour=8, duration_hours=1,
            residual_base_units=200, minimum_observed_days=7,
        )


def test_rejects_boolean_residual_quantity():
    with pytest.raises(ValueError, match="not boolean"):
        recommend_low_traffic_window(
            profile(), current_hour=8, duration_hours=1,
            residual_base_units=True, minimum_observed_days=7,
        )
