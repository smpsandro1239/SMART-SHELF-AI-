import pytest

from app.stockout_risk import StockoutRiskInput, assess_stockout_risk


def test_zero_stock_is_critical():
    result = assess_stockout_risk(StockoutRiskInput(0, 4, 3, 5))
    assert result.risk_level == "CRITICAL"
    assert result.days_of_cover == 0
    assert result.requires_action


def test_demand_exceeds_stock_before_receipt_is_critical():
    result = assess_stockout_risk(StockoutRiskInput(8, 3, 3, 4))
    assert result.risk_level == "CRITICAL"
    assert result.projected_stock_at_receipt == -1


def test_stock_below_safety_buffer_at_receipt_is_high():
    result = assess_stockout_risk(StockoutRiskInput(20, 5, 3, 8))
    assert result.risk_level == "HIGH"
    assert result.projected_stock_at_receipt == 5
    assert result.safety_stock_gap == 3


def test_short_cover_with_buffer_is_medium():
    result = assess_stockout_risk(StockoutRiskInput(20, 4, 3, 4, warning_cover_days=2))
    assert result.risk_level == "MEDIUM"
    assert result.days_of_cover == 5


def test_sufficient_cover_is_low():
    result = assess_stockout_risk(StockoutRiskInput(60, 4, 3, 5))
    assert result.risk_level == "LOW"
    assert not result.requires_action


def test_missing_forecast_is_unknown_not_zero_demand():
    result = assess_stockout_risk(StockoutRiskInput(100, None, 3, None, "INSUFFICIENT_HISTORY"))
    assert result.risk_level == "UNKNOWN"
    assert result.days_of_cover is None
    assert result.requires_action


def test_zero_average_demand_is_not_misclassified_as_low_risk():
    result = assess_stockout_risk(StockoutRiskInput(100, 0, 3, 5))
    assert result.risk_level == "UNKNOWN"


@pytest.mark.parametrize(
    "overrides",
    [
        {"available_quantity": -1},
        {"average_daily_demand": -1},
        {"average_daily_demand": float("nan")},
        {"lead_time_days": 0},
        {"safety_stock": -1},
        {"warning_cover_days": float("inf")},
    ],
)
def test_invalid_inputs_are_rejected(overrides):
    values = {"available_quantity": 10, "average_daily_demand": 2,
              "lead_time_days": 3, "safety_stock": 4}
    values.update(overrides)
    with pytest.raises(ValueError):
        assess_stockout_risk(StockoutRiskInput(**values))
