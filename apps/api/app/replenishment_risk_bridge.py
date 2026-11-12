"""Attach explainable stockout risk to shelf replenishment candidates.

This adapter is deliberately read-only. It requires complete daily sales
coverage and a fresh inventory snapshot; missing data is never treated as zero.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from app.demand_forecasting import DemandForecastInput, forecast_demand
from app.stockout_risk import StockoutRiskInput, assess_stockout_risk


def enrich_replenishment_with_stockout_risk(
    recommendations: Iterable[Mapping[str, Any]],
    daily_sales_records: Iterable[Any],
    *,
    through_date: date,
    now: datetime,
    days: int = 28,
    lead_time_days: float = 3.0,
    target_cover_days: float = 7.0,
    max_inventory_age_minutes: int = 240,
) -> list[dict[str, Any]]:
    """Return copied recommendations enriched with product-level risk evidence."""
    if not isinstance(through_date, date) or isinstance(through_date, datetime):
        raise ValueError("through_date must be a calendar date, not a datetime")
    if not isinstance(now, datetime):
        raise ValueError("now must be a datetime")
    if isinstance(days, bool) or not isinstance(days, int) or not 7 <= days <= 365:
        raise ValueError("days must be between 7 and 365")
    if (isinstance(max_inventory_age_minutes, bool)
            or not isinstance(max_inventory_age_minutes, int)
            or not 1 <= max_inventory_age_minutes <= 10080):
        raise ValueError("max_inventory_age_minutes must be between 1 and 10080")

    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    start_date = through_date - timedelta(days=days - 1)
    grouped: dict[int, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    for record in daily_sales_records:
        product_id = record.product_id
        sales_date = record.sales_date
        quantity = record.quantity
        if isinstance(product_id, bool) or not isinstance(product_id, int):
            raise ValueError("product_id in sales history must be an integer")
        if not isinstance(sales_date, date):
            raise ValueError("sales_date in history must be a date")
        if sales_date < start_date or sales_date > through_date:
            continue
        if isinstance(quantity, bool):
            raise ValueError("daily sales quantity cannot be boolean")
        try:
            numeric_quantity = float(quantity)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("daily sales quantity must be numeric") from exc
        if numeric_quantity < 0 or numeric_quantity != numeric_quantity or numeric_quantity == float("inf"):
            raise ValueError("daily sales quantity must be finite and non-negative")
        grouped[product_id][sales_date] += numeric_quantity

    result: list[dict[str, Any]] = []
    for source in recommendations:
        item = dict(source)
        product_id = item.get("product_id")
        history = grouped.get(product_id, {})
        missing_days = [
            start_date + timedelta(days=offset)
            for offset in range(days)
            if start_date + timedelta(days=offset) not in history
        ]
        item["stockout_risk_level"] = "UNKNOWN"
        item["stockout_risk_status"] = "RISK_UNKNOWN"
        item["stockout_days_of_cover"] = None
        item["stockout_projected_stock_at_receipt"] = None
        item["stockout_safety_stock_gap"] = None
        item["stockout_risk_basis"] = "INSUFFICIENT_EVIDENCE"
        item["stockout_missing_sales_days"] = len(missing_days)
        item["stockout_explanation"] = "Histórico diário incompleto; não é possível avaliar o risco com segurança."

        if missing_days:
            result.append(item)
            continue

        available = item.get("inventory_available_quantity")
        captured_at = item.get("inventory_captured_at")
        if available is None or not isinstance(captured_at, datetime):
            item["stockout_explanation"] = "Snapshot de inventário ausente; confirmar stock antes de classificar o risco."
            result.append(item)
            continue

        captured = captured_at if captured_at.tzinfo is not None else captured_at.replace(tzinfo=timezone.utc)
        age_minutes = (current - captured).total_seconds() / 60.0
        if age_minutes < 0:
            item["stockout_risk_basis"] = "FUTURE_INVENTORY"
            item["stockout_explanation"] = "O snapshot de inventário tem uma data futura; verificar a sincronização dos relógios e atualizar o stock."
            result.append(item)
            continue
        item["stockout_inventory_age_minutes"] = round(age_minutes, 2)
        if age_minutes > max_inventory_age_minutes:
            item["stockout_risk_basis"] = "STALE_INVENTORY"
            item["stockout_explanation"] = "Snapshot de inventário desatualizado; atualizar o stock antes de classificar o risco."
            result.append(item)
            continue

        try:
            if isinstance(available, bool):
                raise ValueError("inventory_available_quantity cannot be boolean")
            forecast = forecast_demand(DemandForecastInput(
                daily_sales=[history[start_date + timedelta(days=offset)] for offset in range(days)],
                lead_time_days=lead_time_days,
                target_cover_days=target_cover_days,
                recent_window_days=days,
                minimum_history_days=7,
            ))
            risk = assess_stockout_risk(StockoutRiskInput(
                available_quantity=float(available),
                average_daily_demand=forecast.average_daily_demand,
                lead_time_days=lead_time_days,
                safety_stock=forecast.safety_stock,
                forecast_status=forecast.status,
            ))
        except (TypeError, ValueError, OverflowError) as exc:
            item["stockout_risk_basis"] = "INVALID_INPUT"
            item["stockout_explanation"] = f"Dados inválidos para avaliar o risco: {exc}"
            result.append(item)
            continue

        item.update({
            "stockout_risk_level": risk.risk_level,
            "stockout_risk_status": risk.status,
            "stockout_days_of_cover": risk.days_of_cover,
            "stockout_projected_stock_at_receipt": risk.projected_stock_at_receipt,
            "stockout_safety_stock_gap": risk.safety_stock_gap,
            "stockout_risk_basis": "DAILY_SALES_AND_FRESH_INVENTORY",
            "stockout_missing_sales_days": 0,
            "stockout_average_daily_demand": forecast.average_daily_demand,
            "stockout_safety_stock": forecast.safety_stock,
            "stockout_reorder_point": forecast.reorder_point,
            "stockout_explanation": risk.explanation,
        })
        result.append(item)
    return result
