"""Historical store-traffic peak detection by weekday and local hour."""
from __future__ import annotations
from collections import defaultdict
from datetime import date
import math
from typing import Any, Iterable

def detect_weekday_hour_traffic_peaks(records: Iterable[Any], *, minimum_observed_days: int = 4,
        minimum_baseline_hours: int = 6, peak_ratio: float = 1.5) -> dict:
    if isinstance(minimum_observed_days, bool) or not isinstance(minimum_observed_days, int) or not 2 <= minimum_observed_days <= 30:
        raise ValueError("minimum_observed_days must be between 2 and 30")
    if isinstance(minimum_baseline_hours, bool) or not isinstance(minimum_baseline_hours, int) or not 1 <= minimum_baseline_hours <= 24:
        raise ValueError("minimum_baseline_hours must be between 1 and 24")
    if isinstance(peak_ratio, bool) or not isinstance(peak_ratio, (int, float)) or not math.isfinite(float(peak_ratio)) or not 1.0 < float(peak_ratio) <= 10.0:
        raise ValueError("peak_ratio must be greater than 1 and at most 10")
    daily: dict[tuple[date, int], int] = defaultdict(int)
    for row in records:
        day, hour, count = row.business_date, row.hour_of_day, row.customer_count
        if not isinstance(day, date):
            raise ValueError("business_date must be a date")
        if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
            raise ValueError("hour_of_day must be between 0 and 23")
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 2_000_000:
            raise ValueError("customer_count must be a non-negative integer")
        daily[(day, hour)] += count
    grouped: dict[tuple[int, int], list[int]] = defaultdict(list)
    for (day, hour), count in daily.items():
        grouped[(day.weekday(), hour)].append(count)
    output, peak_cells = [], []
    for weekday in range(7):
        observed_hour_averages = [
            sum(values) / len(values)
            for hour in range(24)
            if len(values := grouped.get((weekday, hour), [])) >= minimum_observed_days
        ]
        baseline = sum(observed_hour_averages) / len(observed_hour_averages) if len(observed_hour_averages) >= minimum_baseline_hours else None
        for hour in range(24):
            values = grouped.get((weekday, hour), [])
            average = sum(values) / len(values) if values else None
            enough_cell = len(values) >= minimum_observed_days
            ratio = average / baseline if average is not None and baseline is not None and baseline > 0 else None
            is_peak = bool(enough_cell and ratio is not None and ratio >= float(peak_ratio))
            item = {
                "weekday": weekday, "hour_of_day": hour,
                "average_customers": round(average, 3) if average is not None else None,
                "observed_days": len(values),
                "weekday_hour_baseline": round(baseline, 3) if baseline is not None else None,
                "traffic_ratio": round(ratio, 3) if ratio is not None else None,
                "is_peak": is_peak,
                "status": "CLASSIFIED" if enough_cell and baseline is not None else "INSUFFICIENT_DATA",
            }
            output.append(item)
            if is_peak:
                peak_cells.append(item)
    return {
        "method": "WEEKDAY_HOUR_MEAN_VS_OBSERVED_WEEKDAY_HOURLY_BASELINE",
        "minimum_observed_days": minimum_observed_days,
        "minimum_baseline_hours": minimum_baseline_hours,
        "peak_ratio": float(peak_ratio),
        "profile": output, "peaks": peak_cells,
        "automatic_stock_movement_allowed": False,
    }
