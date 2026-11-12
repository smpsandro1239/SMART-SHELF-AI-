"""Read-only multi-pallet prioritisation for store replenishment operations.

This module ranks candidate actions; it never reserves pallets, creates tasks,
changes pallet state, or moves inventory.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping


class PalletPortfolioInputError(ValueError):
    """Invalid candidate data supplied to the portfolio planner."""


@dataclass(frozen=True)
class PalletPortfolioPlan:
    recommendations: tuple[dict[str, Any], ...]
    considered: int
    excluded: int
    automatic_stock_movement_allowed: bool = False


def _number(value: Any, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool):
        raise PalletPortfolioInputError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise PalletPortfolioInputError(f"{field} must be numeric")
    if not math.isfinite(number) or number < minimum:
        raise PalletPortfolioInputError(f"{field} must be finite and >= {minimum}")
    return number


def build_pallet_portfolio_plan(
    candidates: Iterable[Mapping[str, Any]],
    *,
    limit: int = 100,
) -> PalletPortfolioPlan:
    """Rank pallet candidates by service risk, swap feasibility and labour benefit.

    Each candidate must contain a unique positive pallet_id. Missing/invalid
    operational evidence excludes the candidate instead of assuming readiness.
    Required keys: store_id, product_id, pallet_id, residual_base_units,
    pallet_capacity_base_units, threshold_ratio, traffic_level,
    replacement_pallet_available, backroom_capacity_available,
    forecast_consumption_until_low_traffic, conventional_minutes,
    swap_minutes, transport_minutes, rebuild_minutes.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise PalletPortfolioInputError("limit must be an integer between 1 and 500")

    rows = list(candidates)
    seen: set[int] = set()
    ranked: list[dict[str, Any]] = []
    excluded = 0

    for row in rows:
        try:
            pallet_id = row.get("pallet_id")
            if isinstance(pallet_id, bool) or not isinstance(pallet_id, int) or pallet_id <= 0:
                raise PalletPortfolioInputError("pallet_id must be a positive integer")
            if pallet_id in seen:
                raise PalletPortfolioInputError("pallet_id must be unique")
            seen.add(pallet_id)

            store_id = row.get("store_id")
            product_id = row.get("product_id")
            if (isinstance(store_id, bool) or not isinstance(store_id, int) or store_id <= 0
                    or isinstance(product_id, bool) or not isinstance(product_id, int) or product_id <= 0):
                raise PalletPortfolioInputError("store_id and product_id must be positive integers")

            residual = _number(row.get("residual_base_units"), "residual_base_units")
            capacity = _number(row.get("pallet_capacity_base_units"), "pallet_capacity_base_units", minimum=0.000001)
            threshold = _number(row.get("threshold_ratio"), "threshold_ratio")
            forecast = _number(row.get("forecast_consumption_until_low_traffic"), "forecast_consumption_until_low_traffic")
            conventional = _number(row.get("conventional_minutes"), "conventional_minutes")
            swap = _number(row.get("swap_minutes"), "swap_minutes")
            transport = _number(row.get("transport_minutes"), "transport_minutes")
            rebuild = _number(row.get("rebuild_minutes"), "rebuild_minutes")
            if residual > capacity or threshold > 1:
                raise PalletPortfolioInputError("residual/capacity or threshold ratio is out of range")

            traffic = str(row.get("traffic_level", "")).upper()
            if traffic not in {"HIGH", "LOW", "UNKNOWN"}:
                raise PalletPortfolioInputError("traffic_level must be HIGH, LOW or UNKNOWN")
            replacement = row.get("replacement_pallet_available")
            backroom = row.get("backroom_capacity_available")
            if not isinstance(replacement, bool) or not isinstance(backroom, bool):
                raise PalletPortfolioInputError("replacement and backroom flags must be boolean")

            ratio = residual / capacity
            total_swap = swap + transport + rebuild
            saved = conventional - total_swap

            if traffic == "UNKNOWN":
                action, priority, reason = "REVIEW_DATA", 4, "TRAFFIC_UNKNOWN"
            elif forecast > residual:
                action, priority, reason = "INTERIM_REPLENISHMENT", 0, "STOCKOUT_BEFORE_LOW_TRAFFIC"
            elif traffic == "LOW":
                action, priority, reason = "REPLENISH_CURRENT", 3, "LOW_TRAFFIC_NOW"
            elif ratio > threshold:
                action, priority, reason = "REPLENISH_CURRENT", 3, "RESIDUAL_ABOVE_THRESHOLD"
            elif not replacement:
                action, priority, reason = "PREPARE_REPLACEMENT", 2, "NO_READY_REPLACEMENT"
            elif not backroom:
                action, priority, reason = "REVIEW_BACKROOM", 2, "BACKROOM_CAPACITY_UNCONFIRMED"
            elif saved <= 0:
                action, priority, reason = "REPLENISH_CURRENT", 3, "SWAP_NOT_FASTER"
            else:
                action, priority, reason = "SWAP_PALLET", 1, "SWAP_SAVES_LABOUR"

            ranked.append({
                "store_id": store_id,
                "product_id": product_id,
                "pallet_id": pallet_id,
                "action": action,
                "priority": priority,
                "reason_code": reason,
                "residual_ratio": round(ratio, 4),
                "projected_consumption_until_low_traffic": forecast,
                "estimated_minutes_saved": round(saved, 2),
                "estimated_swap_minutes": round(total_swap, 2),
                "traffic_level": traffic,
                "automatic_stock_movement_allowed": False,
            })
        except PalletPortfolioInputError:
            excluded += 1

    ranked.sort(key=lambda item: (
        item["priority"],
        0 if item["action"] == "INTERIM_REPLENISHMENT" else 1,
        -item["estimated_minutes_saved"],
        item["pallet_id"],
    ))
    return PalletPortfolioPlan(tuple(ranked[:limit]), len(ranked), excluded)
