"""Historical low-traffic window selection for pallet rotation.

This is a deterministic planning heuristic over observed local-hour averages.
It is not a demand forecast and never performs stock movements.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class LowTrafficWindowDecision:
    recommendation: str
    reason_code: str
    explanation: str
    start_hour: int | None
    duration_hours: int
    projected_consumption_through_window: float | None
    residual_after_consumption: float | None
    expected_customers_during_window: float | None
    observed_sales_days_min: int
    observed_traffic_days_min: int
    historical_profile_only: bool = True
    automatic_stock_movement_allowed: bool = False


def recommend_low_traffic_window(
    hourly_profile: Sequence[Mapping[str, Any]],
    *,
    current_hour: int,
    duration_hours: int,
    residual_base_units: float,
    minimum_observed_days: int = 7,
) -> LowTrafficWindowDecision:
    if isinstance(current_hour, bool) or not isinstance(current_hour, int) or not 0 <= current_hour <= 23:
        raise ValueError("current_hour must be between 0 and 23")
    if isinstance(duration_hours, bool) or not isinstance(duration_hours, int) or not 1 <= duration_hours <= 4:
        raise ValueError("duration_hours must be between 1 and 4")
    if isinstance(minimum_observed_days, bool) or not isinstance(minimum_observed_days, int) or not 1 <= minimum_observed_days <= 90:
        raise ValueError("minimum_observed_days must be between 1 and 90")
    if isinstance(residual_base_units, bool):
        raise ValueError("residual_base_units must be numeric, not boolean")
    try:
        residual = float(residual_base_units)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("residual_base_units must be finite and non-negative")
    if residual < 0 or residual != residual or residual in (float("inf"), float("-inf")):
        raise ValueError("residual_base_units must be finite and non-negative")
    if len(hourly_profile) != 24:
        raise ValueError("hourly_profile must contain exactly 24 hourly rows")

    by_hour = {}
    for row in hourly_profile:
        if not isinstance(row, Mapping):
            raise ValueError("hourly_profile rows must be mappings")
        hour = row.get("hour_of_day")
        if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23 or hour in by_hour:
            raise ValueError("hourly_profile must contain each hour exactly once")
        by_hour[hour] = row
    if len(by_hour) != 24:
        raise ValueError("hourly_profile must contain each hour exactly once")

    # Require full-day coverage before claiming a globally optimal low-traffic window.
    for row in by_hour.values():
        sales_value = row.get("average_daily_units")
        traffic_value = row.get("average_customers")
        if sales_value is None or traffic_value is None:
            return LowTrafficWindowDecision(
                "INSUFFICIENT_DATA", "HOURLY_PROFILE_INCOMPLETE",
                "O perfil não cobre todas as horas; não é possível afirmar qual é a janela de menor afluência.",
                None, duration_hours, None, None, None, 0, 0,
            )
        try:
            sales_number = float(sales_value)
            traffic_number = float(traffic_value)
            sales_count_raw = row.get("sales_observed_days")
            traffic_count_raw = row.get("traffic_observed_days")
            if (isinstance(sales_count_raw, bool) or not isinstance(sales_count_raw, int)
                    or isinstance(traffic_count_raw, bool) or not isinstance(traffic_count_raw, int)):
                raise ValueError("hourly profile coverage counts must be integers")
            sales_count = sales_count_raw
            traffic_count = traffic_count_raw
        except (TypeError, ValueError, OverflowError):
            raise ValueError("hourly profile values must be numeric and coverage counts must be integers")
        if (isinstance(sales_value, bool) or isinstance(traffic_value, bool)
                or not math.isfinite(sales_number) or sales_number < 0
                or not math.isfinite(traffic_number) or traffic_number < 0
                or sales_count < minimum_observed_days or traffic_count < minimum_observed_days):
            return LowTrafficWindowDecision(
                "INSUFFICIENT_DATA", "HOURLY_PROFILE_INCOMPLETE",
                "Existem horas com valores inválidos ou cobertura histórica abaixo do mínimo exigido.",
                None, duration_hours, None, None, None, 0, 0,
            )

    candidates = []
    missing_sales = False
    missing_traffic = False
    insufficient_coverage = False
    for offset in range(1, 25):
        consumption_hours = [(current_hour + step) % 24 for step in range(offset + duration_hours)]
        window_hours = [(current_hour + offset + step) % 24 for step in range(duration_hours)]
        demand_values = []
        traffic_values = []
        sales_days = []
        traffic_days = []
        for hour in consumption_hours:
            row = by_hour[hour]
            value = row.get("average_daily_units")
            observed = row.get("sales_observed_days") or 0
            if value is None:
                missing_sales = True
                demand_values = []
                break
            if observed < minimum_observed_days:
                insufficient_coverage = True
                demand_values = []
                break
            demand_values.append(float(value))
            sales_days.append(observed)
        if len(demand_values) != len(consumption_hours):
            continue
        for hour in window_hours:
            row = by_hour[hour]
            value = row.get("average_customers")
            observed = row.get("traffic_observed_days") or 0
            if value is None:
                missing_traffic = True
                traffic_values = []
                break
            if observed < minimum_observed_days:
                insufficient_coverage = True
                traffic_values = []
                break
            traffic_values.append(float(value))
            traffic_days.append(observed)
        if len(traffic_values) != len(window_hours):
            continue
        projected = sum(demand_values)
        if projected > residual:
            continue
        candidates.append({
            "offset": offset,
            "start_hour": (current_hour + offset) % 24,
            "projected": projected,
            "remaining": residual - projected,
            "customers": sum(traffic_values),
            "sales_days": min(sales_days),
            "traffic_days": min(traffic_days),
        })

    if not candidates:
        if missing_sales or missing_traffic or insufficient_coverage:
            return LowTrafficWindowDecision(
                "INSUFFICIENT_DATA", "HOURLY_PROFILE_INCOMPLETE",
                "Não existem observações horárias suficientes para avaliar todas as janelas candidatas.",
                None, duration_hours, None, None, None, 0, 0,
            )
        return LowTrafficWindowDecision(
            "REPLENISH_CURRENT", "RESIDUAL_CANNOT_REACH_WINDOW",
            "O stock residual não cobre o consumo histórico esperado até uma janela operacional elegível.",
            None, duration_hours, None, None, None, 0, 0,
        )

    best = min(candidates, key=lambda item: (item["customers"], item["offset"]))
    return LowTrafficWindowDecision(
        "WAIT_FOR_LOW_TRAFFIC", "LOWEST_OBSERVED_TRAFFIC_WINDOW",
        "Janela selecionada pela menor afluência histórica, desde que o stock residual cubra o consumo até ao início.",
        best["start_hour"], duration_hours, best["projected"], best["remaining"],
        best["customers"], best["sales_days"], best["traffic_days"],
    )
