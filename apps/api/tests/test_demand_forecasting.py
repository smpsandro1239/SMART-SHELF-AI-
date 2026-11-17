import pytest

from app.demand_forecasting import DemandForecastInput, forecast_demand


def test_forecast_returns_insufficient_history_without_inventing_demand():
    result = forecast_demand(DemandForecastInput(
        daily_sales=[2, 3, 1], lead_time_days=2,
    ))

    assert result.status == "INSUFFICIENT_HISTORY"
    assert result.average_daily_demand is None
    assert result.reorder_point is None


def test_forecast_calculates_weighted_average_and_stock_thresholds():
    result = forecast_demand(DemandForecastInput(
        daily_sales=[1, 1, 1, 1, 1, 1, 1],
        lead_time_days=2,
        target_cover_days=5,
        service_factor=1.65,
    ))

    assert result.status == "FORECAST_READY"
    assert result.average_daily_demand == 1
    assert result.daily_demand_stddev == 0
    assert result.expected_lead_time_demand == 2
    assert result.safety_stock == 0
    assert result.reorder_point == 2
    assert result.target_stock == 7


def test_recent_days_receive_more_weight_than_old_days():
    result = forecast_demand(DemandForecastInput(
        daily_sales=[0, 0, 0, 0, 0, 0, 7],
        lead_time_days=1,
        service_factor=0,
    ))

    assert result.average_daily_demand > 1
    assert result.average_daily_demand < 7


def test_forecast_includes_safety_stock_when_demand_is_volatile():
    result = forecast_demand(DemandForecastInput(
        daily_sales=[0, 2, 0, 2, 0, 2, 0],
        lead_time_days=4,
        service_factor=1.65,
    ))

    assert result.daily_demand_stddev > 0
    assert result.safety_stock > 0
    assert result.reorder_point > result.expected_lead_time_demand


@pytest.mark.parametrize(
    "overrides",
    [
        {"daily_sales": [1, 2, -1, 3, 4, 5, 6]},
        {"daily_sales": [1, 2, 3, 4, 5, 6, float("nan")]},
        {"lead_time_days": 0},
        {"lead_time_days": float("inf")},
        {"target_cover_days": 0},
        {"service_factor": 4.1},
        {"recent_window_days": 1},
        {"minimum_history_days": 29},
    ],
)
def test_forecast_rejects_invalid_inputs(overrides):
    values = {
        "daily_sales": [1, 2, 3, 4, 5, 6, 7],
        "lead_time_days": 2,
    }
    values.update(overrides)
    with pytest.raises(ValueError):
        forecast_demand(DemandForecastInput(**values))


def test_forecast_uses_only_configured_recent_window():
    result = forecast_demand(DemandForecastInput(
        daily_sales=[100] * 7 + [1] * 7,
        lead_time_days=2,
        recent_window_days=7,
        minimum_history_days=7,
        service_factor=0,
    ))

    assert result.average_daily_demand == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"recent_window_days": 2.5},
        {"recent_window_days": True},
        {"minimum_history_days": 3.5},
        {"minimum_history_days": False},
    ],
)
def test_forecast_requires_integer_history_window_parameters(overrides):
    values = {
        "daily_sales": [1, 2, 3, 4, 5, 6, 7],
        "lead_time_days": 2,
    }
    values.update(overrides)
    with pytest.raises(ValueError):
        forecast_demand(DemandForecastInput(**values))
