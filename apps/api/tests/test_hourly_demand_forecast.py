from datetime import date
from types import SimpleNamespace

import pytest

from app.hourly_demand_forecast import forecast_hourly_demand


def _rows(start: date, weeks: int, quantity_fn=None):
    result = []
    for week in range(weeks):
        day = start + __import__("datetime").timedelta(days=week * 7)
        for hour in range(24):
            quantity = quantity_fn(week, hour) if quantity_fn else week + 1
            result.append(SimpleNamespace(business_date=day, hour_of_day=hour, quantity=quantity))
    return result


def test_forecast_uses_recent_weekday_hour_history_and_preserves_zero():
    start = date(2026, 1, 5)  # Monday
    rows = _rows(start, 5, lambda week, hour: 0 if week == 4 and hour == 8 else 10 + week)
    result = forecast_hourly_demand(
        rows, forecast_start=date(2026, 2, 9), horizon_days=1,
        minimum_observed_days=4, max_seasonal_samples=5,
    )
    monday_8 = result["forecasts"][8]
    assert monday_8["predicted_units"] is not None
    assert monday_8["observed_days"] == 5
    assert monday_8["confidence"] == "MEDIUM"
    assert result["model_type"] == "HISTORICAL_SEASONAL_BASELINE"


def test_forecast_does_not_invent_values_for_missing_hours():
    result = forecast_hourly_demand(
        [], forecast_start=date(2026, 11, 16), horizon_days=1,
        minimum_observed_days=2,
    )
    assert len(result["forecasts"]) == 24
    assert all(row["predicted_units"] is None for row in result["forecasts"])
    assert all(row["confidence"] == "INSUFFICIENT_DATA" for row in result["forecasts"])


def test_forecast_backtest_reports_metrics_when_history_is_sufficient():
    rows = _rows(date(2026, 1, 5), 8)
    result = forecast_hourly_demand(
        rows, forecast_start=date(2026, 3, 2), horizon_days=2,
        minimum_observed_days=3, max_seasonal_samples=5,
    )
    assert result["backtest"]["points"] > 0
    assert result["backtest"]["mae_units"] is not None
    assert result["backtest"]["status"] == "AVAILABLE"


@pytest.mark.parametrize("kwargs", [
    {"horizon_days": 0},
    {"horizon_days": 15},
    {"minimum_observed_days": 1},
    {"max_seasonal_samples": 1},
    {"recent_weight": 0},
    {"recent_weight": 1.1},
])
def test_forecast_rejects_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        forecast_hourly_demand([], forecast_start=date(2026, 11, 16), **kwargs)


def test_forecast_rejects_negative_or_non_finite_history():
    bad = [SimpleNamespace(business_date=date(2026, 11, 9), hour_of_day=8, quantity=float("nan"))]
    with pytest.raises(ValueError):
        forecast_hourly_demand(bad, forecast_start=date(2026, 11, 16))


def test_forecast_excludes_observations_on_or_after_forecast_start():
    start = date(2026, 1, 5)
    history = _rows(start, 4, lambda _week, _hour: 8)
    future = _rows(date(2026, 2, 2), 1, lambda _week, _hour: 999)
    result = forecast_hourly_demand(
        history + future,
        forecast_start=date(2026, 2, 2),
        horizon_days=1,
        minimum_observed_days=4,
        max_seasonal_samples=4,
    )
    assert result["forecasts"][8]["observed_days"] == 4
    assert result["forecasts"][8]["predicted_units"] == pytest.approx(8)


def test_four_observations_are_low_confidence_not_medium():
    rows = _rows(date(2026, 1, 5), 4, lambda _week, _hour: 3)
    result = forecast_hourly_demand(
        rows,
        forecast_start=date(2026, 2, 2),
        horizon_days=1,
        minimum_observed_days=4,
        max_seasonal_samples=4,
    )
    assert result["forecasts"][8]["confidence"] == "LOW"


def test_zero_demand_backtest_does_not_divide_by_zero():
    rows = _rows(date(2026, 1, 5), 6, lambda _week, _hour: 0)
    result = forecast_hourly_demand(
        rows,
        forecast_start=date(2026, 2, 16),
        horizon_days=1,
        minimum_observed_days=3,
        max_seasonal_samples=4,
    )
    assert result["backtest"]["mae_units"] == 0
    assert result["backtest"]["wape"] is None


@pytest.mark.parametrize("quantity", [True, False])
def test_forecast_rejects_boolean_hourly_quantities(quantity):
    rows = [SimpleNamespace(
        business_date=date(2026, 11, 9), hour_of_day=8, quantity=quantity
    )]
    with pytest.raises(ValueError, match="not boolean"):
        forecast_hourly_demand(
            rows, forecast_start=date(2026, 11, 16), horizon_days=1
        )


def test_forecast_aggregates_multiple_records_for_same_business_hour():
    day = date(2026, 11, 9)
    history = [
        SimpleNamespace(business_date=day, hour_of_day=8, quantity=3),
        SimpleNamespace(business_date=day, hour_of_day=8, quantity=4),
    ]
    for week in range(1, 4):
        observed_day = day - __import__("datetime").timedelta(days=7 * week)
        history.append(SimpleNamespace(
            business_date=observed_day, hour_of_day=8, quantity=7
        ))
    result = forecast_hourly_demand(
        history, forecast_start=date(2026, 12, 7), horizon_days=1,
        minimum_observed_days=4, max_seasonal_samples=4,
    )
    assert result["forecasts"][8]["observed_days"] == 4
    assert result["forecasts"][8]["predicted_units"] == pytest.approx(7)
