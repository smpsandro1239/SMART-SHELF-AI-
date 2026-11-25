"""Transparent weekday/hour seasonal baseline and rolling-origin backtest.

This is a statistical baseline, not a trained machine-learning model.
Missing observations are never imputed as zero.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import math
from typing import Any, Iterable


MODEL_VERSION = "SEASONAL_WEEKDAY_HOUR_BASELINE_V1"


def _daily_observations(records: Iterable[Any]) -> dict[tuple[date, int], float]:
    grouped: dict[tuple[date, int], float] = defaultdict(float)
    for row in records:
        day = row.business_date
        hour = row.hour_of_day
        if isinstance(row.quantity, bool):
            raise ValueError("Hourly quantity must be numeric, not boolean")
        try:
            quantity = float(row.quantity)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Hourly quantity must be numeric") from exc
        if not isinstance(day, date):
            raise ValueError("business_date must be a date")
        if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
            raise ValueError("hour_of_day must be between 0 and 23")
        if not math.isfinite(quantity) or quantity < 0:
            raise ValueError("Hourly quantity must be finite and non-negative")
        grouped[(day, hour)] += quantity
    return dict(grouped)


def _weighted_seasonal_average(values: list[tuple[date, float]], target_date: date,
                               recent_weight: float) -> float:
    ordered = sorted(values, key=lambda item: item[0], reverse=True)
    weighted_total = 0.0
    weight_total = 0.0
    for age, (_day, quantity) in enumerate(ordered):
        weight = recent_weight ** age
        weighted_total += quantity * weight
        weight_total += weight
    return weighted_total / weight_total


def forecast_hourly_demand(
    records: Iterable[Any],
    *,
    forecast_start: date,
    horizon_days: int = 7,
    minimum_observed_days: int = 4,
    max_seasonal_samples: int = 8,
    recent_weight: float = 0.85,
) -> dict:
    if not isinstance(forecast_start, date):
        raise ValueError("forecast_start must be a date")
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or not 1 <= horizon_days <= 14:
        raise ValueError("horizon_days must be between 1 and 14")
    if isinstance(minimum_observed_days, bool) or not isinstance(minimum_observed_days, int) or not 2 <= minimum_observed_days <= 30:
        raise ValueError("minimum_observed_days must be between 2 and 30")
    if isinstance(max_seasonal_samples, bool) or not isinstance(max_seasonal_samples, int) or not minimum_observed_days <= max_seasonal_samples <= 16:
        raise ValueError("max_seasonal_samples must be between minimum_observed_days and 16")
    if isinstance(recent_weight, bool) or not isinstance(recent_weight, (int, float)) or not 0 < recent_weight <= 1:
        raise ValueError("recent_weight must be in (0, 1]")

    daily = _daily_observations(records)
    grouped: dict[tuple[int, int], list[tuple[date, float]]] = defaultdict(list)
    for (day, hour), quantity in daily.items():
        if day < forecast_start:
            grouped[(day.weekday(), hour)].append((day, quantity))

    forecasts = []
    for offset in range(horizon_days):
        target = forecast_start + timedelta(days=offset)
        for hour in range(24):
            history = sorted(grouped.get((target.weekday(), hour), []), key=lambda item: item[0], reverse=True)
            sample = history[:max_seasonal_samples]
            available = len(sample)
            predicted = None
            confidence = "INSUFFICIENT_DATA"
            if available >= minimum_observed_days:
                predicted = round(_weighted_seasonal_average(sample, target, float(recent_weight)), 3)
                confidence = "HIGH" if available >= 8 else "MEDIUM" if available >= 5 else "LOW"
            forecasts.append({
                "forecast_date": target,
                "weekday": target.weekday(),
                "hour_of_day": hour,
                "predicted_units": predicted,
                "observed_days": available,
                "confidence": confidence,
            })

    errors = []
    absolute_error_total = 0.0
    actual_total = 0.0
    backtest_points = 0
    for (weekday, hour), observations in grouped.items():
        ordered = sorted(observations, key=lambda item: item[0])
        for index in range(minimum_observed_days, len(ordered)):
            train = ordered[max(0, index - max_seasonal_samples):index]
            if len(train) < minimum_observed_days:
                continue
            actual = ordered[index][1]
            predicted = _weighted_seasonal_average(train, ordered[index][0], float(recent_weight))
            absolute_error = abs(actual - predicted)
            absolute_error_total += absolute_error
            actual_total += abs(actual)
            errors.append(absolute_error)
            backtest_points += 1

    mae = round(sum(errors) / len(errors), 3) if errors else None
    wape = round(absolute_error_total / actual_total, 4) if actual_total > 0 else None
    return {
        "model_version": MODEL_VERSION,
        "model_type": "HISTORICAL_SEASONAL_BASELINE",
        "forecast_start": forecast_start,
        "forecast_end": forecast_start + timedelta(days=horizon_days - 1),
        "horizon_days": horizon_days,
        "minimum_observed_days": minimum_observed_days,
        "max_seasonal_samples": max_seasonal_samples,
        "recent_weight": float(recent_weight),
        "forecasts": forecasts,
        "backtest": {
            "method": "ROLLING_ORIGIN_SAME_WEEKDAY_HOUR",
            "points": backtest_points,
            "mae_units": mae,
            "wape": wape,
            "status": "AVAILABLE" if backtest_points else "INSUFFICIENT_HISTORY",
        },
        "automatic_stock_movement_allowed": False,
    }
