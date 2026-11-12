from datetime import date
from types import SimpleNamespace
import pytest

from app.hourly_patterns import build_weekday_hour_profile


def test_weekday_hour_profile_averages_only_observed_days_and_preserves_zero():
    sales = [
        SimpleNamespace(business_date=date(2026, 11, 2), hour_of_day=8, quantity=10),
        SimpleNamespace(business_date=date(2026, 11, 9), hour_of_day=8, quantity=0),
    ]
    traffic = [
        SimpleNamespace(business_date=date(2026, 11, 2), hour_of_day=8, customer_count=100),
        SimpleNamespace(business_date=date(2026, 11, 9), hour_of_day=8, customer_count=0),
    ]
    rows = build_weekday_hour_profile(sales, traffic)
    monday_8 = rows[8]
    assert monday_8["weekday_name"] == "MONDAY"
    assert monday_8["average_daily_units"] == 5
    assert monday_8["sales_observed_days"] == 2
    assert monday_8["average_customers"] == 50
    assert monday_8["traffic_observed_days"] == 2


def test_weekday_hour_profile_does_not_fill_missing_hours_with_zero():
    rows = build_weekday_hour_profile([], [])
    assert len(rows) == 168
    assert rows[0]["average_daily_units"] is None
    assert rows[0]["average_customers"] is None
    assert rows[0]["sales_observed_days"] == 0


def test_weekday_hour_profile_keeps_weekdays_separate():
    sales = [
        SimpleNamespace(business_date=date(2026, 11, 2), hour_of_day=10, quantity=4),
        SimpleNamespace(business_date=date(2026, 11, 3), hour_of_day=10, quantity=12),
    ]
    rows = build_weekday_hour_profile(sales, [])
    assert rows[10]["average_daily_units"] == 4
    assert rows[24 + 10]["average_daily_units"] == 12


def test_weekday_hour_profile_rejects_negative_values():
    sales = [SimpleNamespace(business_date=date(2026, 11, 2), hour_of_day=8, quantity=-1)]
    with pytest.raises(ValueError):
        build_weekday_hour_profile(sales, [])
