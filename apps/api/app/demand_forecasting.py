"""Explainable daily-demand forecast and stock-policy calculation.

The module is deliberately independent from POS/ERP integrations. Callers must
supply one sales quantity for every calendar day, including zero-sales days.
Results are planning estimates, never confirmed sales or stock movements.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Sequence


@dataclass(frozen=True)
class DemandForecastInput:
    daily_sales: Sequence[float]
    lead_time_days: float
    target_cover_days: float = 7.0
    service_factor: float = 1.65
    recent_window_days: int = 28
    minimum_history_days: int = 7


@dataclass(frozen=True)
class DemandForecast:
    status: str
    history_days: int
    average_daily_demand: float | None
    daily_demand_stddev: float | None
    expected_lead_time_demand: float | None
    safety_stock: float | None
    reorder_point: float | None
    target_stock: float | None
    explanation: str


def _finite_nonnegative(name: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(float(value)) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return float(value)


def forecast_demand(data: DemandForecastInput) -> DemandForecast:
    """Estimate demand and reorder thresholds from consecutive daily sales.

    A linearly weighted average favours recent days. Safety stock is estimated
    with the sample standard deviation and a caller-selected service factor:
    z * daily_stddev * sqrt(lead_time_days).
    """
    if not isinstance(data.daily_sales, Sequence) or isinstance(data.daily_sales, (str, bytes)):
        raise ValueError("daily_sales must be a sequence of daily quantities")
    if (isinstance(data.recent_window_days, bool)
            or not isinstance(data.recent_window_days, int)
            or data.recent_window_days < 2 or data.recent_window_days > 365):
        raise ValueError("recent_window_days must be an integer between 2 and 365")
    if (isinstance(data.minimum_history_days, bool)
            or not isinstance(data.minimum_history_days, int)
            or data.minimum_history_days < 2):
        raise ValueError("minimum_history_days must be an integer of at least 2")
    if data.minimum_history_days > data.recent_window_days:
        raise ValueError("minimum_history_days cannot exceed recent_window_days")

    lead_time = _finite_nonnegative("lead_time_days", data.lead_time_days)
    if lead_time <= 0:
        raise ValueError("lead_time_days must be positive")
    cover_days = _finite_nonnegative("target_cover_days", data.target_cover_days)
    if cover_days <= 0:
        raise ValueError("target_cover_days must be positive")
    service_factor = _finite_nonnegative("service_factor", data.service_factor)
    if service_factor > 4:
        raise ValueError("service_factor cannot exceed 4")

    sales = [_finite_nonnegative(f"daily_sales[{i}]", value)
             for i, value in enumerate(data.daily_sales)]
    if len(sales) < data.minimum_history_days:
        return DemandForecast(
            "INSUFFICIENT_HISTORY", len(sales), None, None, None, None, None, None,
            f"São necessários pelo menos {data.minimum_history_days} dias consecutivos de vendas.",
        )

    window = sales[-data.recent_window_days:]
    weights = list(range(1, len(window) + 1))
    average = sum(qty * weight for qty, weight in zip(window, weights)) / sum(weights)
    deviation = statistics.stdev(window) if len(window) > 1 else 0.0
    lead_demand = average * lead_time
    safety = service_factor * deviation * math.sqrt(lead_time)
    reorder_point = lead_demand + safety
    target_stock = average * (lead_time + cover_days) + safety

    return DemandForecast(
        "FORECAST_READY", len(sales), round(average, 4), round(deviation, 4),
        round(lead_demand, 4), round(safety, 4), round(reorder_point, 4),
        round(target_stock, 4),
        "Estimativa baseada em média móvel ponderada recente e variabilidade diária; validar sazonalidade, promoções e ruturas antes de automatizar encomendas.",
    )
