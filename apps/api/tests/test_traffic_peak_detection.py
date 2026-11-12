from datetime import date, timedelta
from types import SimpleNamespace
import pytest
from app.traffic_peak_detection import detect_weekday_hour_traffic_peaks

def _traffic_rows(weeks=4):
    rows, monday = [], date(2026, 1, 5)
    for week in range(weeks):
        day = monday + timedelta(days=week * 7)
        for hour in range(8):
            rows.append(SimpleNamespace(business_date=day, hour_of_day=hour, customer_count=10))
        rows.append(SimpleNamespace(business_date=day, hour_of_day=8, customer_count=40))
    return rows

def test_detects_peak_against_same_weekday_observed_hour_baseline():
    result = detect_weekday_hour_traffic_peaks(_traffic_rows(), minimum_observed_days=4, minimum_baseline_hours=6)
    row = next(x for x in result["profile"] if x["weekday"] == 0 and x["hour_of_day"] == 8)
    assert row["is_peak"] is True
    assert row["traffic_ratio"] > 1.5
    assert row["observed_days"] == 4

def test_missing_hours_are_not_zero_or_classified():
    result = detect_weekday_hour_traffic_peaks([], minimum_observed_days=4)
    row = next(x for x in result["profile"] if x["weekday"] == 0 and x["hour_of_day"] == 8)
    assert row["average_customers"] is None
    assert row["weekday_hour_baseline"] is None
    assert row["is_peak"] is False
    assert row["status"] == "INSUFFICIENT_DATA"

def test_zero_traffic_is_preserved():
    rows = [SimpleNamespace(business_date=date(2026, 1, 5) + timedelta(days=7*w), hour_of_day=h, customer_count=0)
            for w in range(4) for h in range(8)]
    result = detect_weekday_hour_traffic_peaks(rows, minimum_observed_days=4, minimum_baseline_hours=6)
    row = next(x for x in result["profile"] if x["weekday"] == 0 and x["hour_of_day"] == 0)
    assert row["average_customers"] == 0
    assert row["status"] == "CLASSIFIED"
    assert row["is_peak"] is False

@pytest.mark.parametrize("kwargs", [
    {"minimum_observed_days": 1}, {"minimum_baseline_hours": 0},
    {"peak_ratio": 1}, {"peak_ratio": float("nan")},
])
def test_rejects_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        detect_weekday_hour_traffic_peaks([], **kwargs)

def test_rejects_negative_customer_counts():
    rows = [SimpleNamespace(business_date=date(2026, 1, 5), hour_of_day=8, customer_count=-1)]
    with pytest.raises(ValueError):
        detect_weekday_hour_traffic_peaks(rows)
