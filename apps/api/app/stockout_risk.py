"""Explainable stockout-risk assessment from available stock and demand forecasts.

This module produces a deterministic operational risk band, not a calibrated
probability. It does not mutate inventory or create replenishment tasks.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class StockoutRiskInput:
    available_quantity: float
    average_daily_demand: float | None
    lead_time_days: float
    safety_stock: float | None
    forecast_status: str = "FORECAST_READY"
    warning_cover_days: float = 2.0


@dataclass(frozen=True)
class StockoutRisk:
    status: str
    risk_level: str
    days_of_cover: float | None
    projected_stock_at_receipt: float | None
    safety_stock_gap: float | None
    requires_action: bool
    explanation: str


def _number(name: str, value: float, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (not allow_zero and result == 0):
        qualifier = "positive" if not allow_zero else "finite and non-negative"
        raise ValueError(f"{name} must be {qualifier}")
    return result


def assess_stockout_risk(data: StockoutRiskInput) -> StockoutRisk:
    """Classify risk using stock cover, lead time and the safety-stock buffer."""
    available = _number("available_quantity", data.available_quantity)
    lead_time = _number("lead_time_days", data.lead_time_days, allow_zero=False)
    warning_days = _number("warning_cover_days", data.warning_cover_days)
    if data.forecast_status != "FORECAST_READY":
        return StockoutRisk("RISK_UNKNOWN", "UNKNOWN", None, None, None, True,
                            "Não existe previsão válida; não é possível classificar o risco de rutura.")
    if data.average_daily_demand is None or data.safety_stock is None:
        return StockoutRisk("RISK_UNKNOWN", "UNKNOWN", None, None, None, True,
                            "A previsão não contém procura média e stock de segurança suficientes.")
    average = _number("average_daily_demand", data.average_daily_demand)
    safety = _number("safety_stock", data.safety_stock)
    if average == 0:
        return StockoutRisk("RISK_UNKNOWN", "UNKNOWN", None, available,
                            max(0.0, safety - available), False,
                            "A procura média estimada é zero; validar o histórico antes de classificar o risco.")
    days_cover = available / average
    projected = available - average * lead_time
    safety_gap = max(0.0, safety - projected)
    if available == 0 or projected < 0:
        level = "CRITICAL"
        explanation = "O stock disponível não cobre a procura estimada até à receção; requer intervenção prioritária."
    elif projected < safety:
        level = "HIGH"
        explanation = "O stock deverá cobrir o prazo de abastecimento, mas ficará abaixo do stock de segurança."
    elif days_cover <= lead_time + warning_days:
        level = "MEDIUM"
        explanation = "A cobertura de stock é curta face ao prazo de abastecimento e à margem de aviso configurada."
    else:
        level = "LOW"
        explanation = "A cobertura estimada ultrapassa o prazo de abastecimento e preserva o stock de segurança."
    return StockoutRisk("RISK_ASSESSED", level, round(days_cover, 4),
                        round(projected, 4), round(safety_gap, 4),
                        level in {"CRITICAL", "HIGH", "MEDIUM"}, explanation)
