"""Weekday-by-hour historical aggregation without imputing missing observations."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
from typing import Iterable, Any

WEEKDAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")


def build_weekday_hour_profile(sales_records: Iterable[Any], traffic_records: Iterable[Any]) -> list[dict]:
    sales_by_day_hour = defaultdict(float)
    traffic_by_day_hour = defaultdict(float)

    for row in sales_records:
        business_date = row.business_date
        hour = row.hour_of_day
        quantity = float(row.quantity)
        if not isinstance(business_date, date) or isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
            raise ValueError("Invalid hourly sales record date or hour")
        if not math.isfinite(quantity) or quantity < 0:
            raise ValueError("Hourly sales quantity must be finite and non-negative")
        sales_by_day_hour[(business_date.weekday(), hour, business_date)] += quantity

    for row in traffic_records:
        business_date = row.business_date
        hour = row.hour_of_day
        count = int(row.customer_count)
        if not isinstance(business_date, date) or isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
            raise ValueError("Invalid hourly traffic record date or hour")
        if count < 0:
            raise ValueError("Customer count must be non-negative")
        traffic_by_day_hour[(business_date.weekday(), hour, business_date)] += count

    sales_groups = defaultdict(list)
    traffic_groups = defaultdict(list)
    for (weekday, hour, _business_date), quantity in sales_by_day_hour.items():
        sales_groups[(weekday, hour)].append(quantity)
    for (weekday, hour, _business_date), count in traffic_by_day_hour.items():
        traffic_groups[(weekday, hour)].append(count)

    profile = []
    for weekday in range(7):
        for hour in range(24):
            sales = sales_groups.get((weekday, hour), [])
            traffic = traffic_groups.get((weekday, hour), [])
            profile.append({
                "weekday": weekday,
                "weekday_name": WEEKDAYS[weekday],
                "hour_of_day": hour,
                "average_daily_units": sum(sales) / len(sales) if sales else None,
                "sales_observed_days": len(sales),
                "average_customers": sum(traffic) / len(traffic) if traffic else None,
                "traffic_observed_days": len(traffic),
            })
    return profile
