"""Consultative pallet rotation decisions; this module never mutates stock."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


class PalletRotationInputError(ValueError):
    """Invalid simulation input."""


def _decimal(value: Any, field: str, *, allow_zero: bool = True) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise PalletRotationInputError(f"{field} must be a valid number")
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        raise PalletRotationInputError(f"{field} must be finite and valid")
    return number


@dataclass(frozen=True)
class PalletRotationDecision:
    recommendation: str
    reason_code: str
    explanation: str
    residual_ratio: float
    threshold_ratio: float
    conventional_cost: float | None
    swap_cost: float | None
    estimated_minutes_saved: float | None
    inputs_complete: bool
    automatic_stock_movement_allowed: bool = False


def evaluate_pallet_rotation(
    *,
    product_eligible: bool,
    residual_base_units: Any,
    pallet_capacity_base_units: Any,
    threshold_ratio: Any = 0.5,
    traffic_level: str,
    replacement_pallet_available: bool,
    backroom_capacity_available: bool,
    conventional_replenishment_minutes: Any | None,
    pallet_swap_minutes: Any | None,
    transport_minutes: Any | None,
    pallet_rebuild_minutes: Any | None,
    labour_cost_per_hour: Any | None = None,
    forecast_consumption_until_low_traffic: Any | None = None,
) -> PalletRotationDecision:
    """Compare conventional replenishment with a complete pallet exchange.

    Quantities are expressed in the product base unit. Costs currently include
    labour only; this is a simulation, not an execution or stock movement API.
    """
    for name, value in (
        ("product_eligible", product_eligible),
        ("replacement_pallet_available", replacement_pallet_available),
        ("backroom_capacity_available", backroom_capacity_available),
    ):
        if not isinstance(value, bool):
            raise PalletRotationInputError(f"{name} must be boolean")

    traffic = str(traffic_level).upper()
    if traffic not in {"HIGH", "LOW", "UNKNOWN"}:
        raise PalletRotationInputError("traffic_level must be HIGH, LOW or UNKNOWN")

    residual = _decimal(residual_base_units, "residual_base_units")
    capacity = _decimal(pallet_capacity_base_units, "pallet_capacity_base_units", allow_zero=False)
    threshold = _decimal(threshold_ratio, "threshold_ratio")
    if threshold > 1:
        raise PalletRotationInputError("threshold_ratio must be between 0 and 1")
    if residual > capacity:
        raise PalletRotationInputError("residual quantity cannot exceed pallet capacity")

    ratio = residual / capacity

    def decision(code: str, reason: str, explanation: str, *, conventional=None,
                 swap=None, saved=None, complete=True):
        return PalletRotationDecision(
            code, reason, explanation, float(ratio), float(threshold),
            conventional, swap, saved, complete,
        )

    if not product_eligible:
        return decision("NOT_ELIGIBLE", "PRODUCT_NOT_CONFIGURED",
                        "O produto não está configurado para exposição e troca por palete.")
    if traffic == "UNKNOWN":
        return decision("INSUFFICIENT_DATA", "TRAFFIC_UNKNOWN",
                        "A afluência atual é desconhecida; não é possível escolher a janela operacional.",
                        complete=False)
    if traffic == "LOW":
        return decision("REPLENISH_CURRENT", "LOW_TRAFFIC_WINDOW",
                        "A afluência é baixa; privilegiar a reposição da palete atual.")
    if ratio > threshold:
        return decision("REPLENISH_CURRENT", "RESIDUAL_ABOVE_THRESHOLD",
                        "A quantidade residual ainda está acima do limiar de troca.")
    if not replacement_pallet_available:
        return decision("REPLENISH_CURRENT", "NO_READY_REPLACEMENT",
                        "Não existe uma palete completa preparada para troca.")
    if not backroom_capacity_available:
        return decision("REPLENISH_CURRENT", "NO_SAFE_BACKROOM_CAPACITY",
                        "Não existe capacidade confirmada para guardar a palete parcial.")

    required = {
        "conventional_replenishment_minutes": conventional_replenishment_minutes,
        "pallet_swap_minutes": pallet_swap_minutes,
        "transport_minutes": transport_minutes,
        "pallet_rebuild_minutes": pallet_rebuild_minutes,
        "labour_cost_per_hour": labour_cost_per_hour,
        "forecast_consumption_until_low_traffic": forecast_consumption_until_low_traffic,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        return decision("INSUFFICIENT_DATA", "MISSING_COST_OR_DEMAND_INPUT",
                        "Faltam dados para comparar custos e cobertura: " + ", ".join(missing),
                        complete=False)

    conventional_minutes = _decimal(conventional_replenishment_minutes, "conventional_replenishment_minutes")
    swap_minutes = _decimal(pallet_swap_minutes, "pallet_swap_minutes")
    travel_minutes = _decimal(transport_minutes, "transport_minutes")
    rebuild_minutes = _decimal(pallet_rebuild_minutes, "pallet_rebuild_minutes")
    hourly_cost = _decimal(labour_cost_per_hour, "labour_cost_per_hour")
    forecast = _decimal(forecast_consumption_until_low_traffic, "forecast_consumption_until_low_traffic")

    if forecast > residual:
        return decision("WAIT_FOR_LOW_TRAFFIC", "RESIDUAL_CANNOT_COVER_DEMAND",
                        "O stock residual não cobre a procura prevista até à próxima janela de baixa afluência.")

    conventional_cost = conventional_minutes * hourly_cost / Decimal("60")
    total_swap_minutes = swap_minutes + travel_minutes + rebuild_minutes
    swap_cost = total_swap_minutes * hourly_cost / Decimal("60")
    saved = conventional_minutes - total_swap_minutes

    if swap_cost >= conventional_cost:
        return decision("NOT_ECONOMICAL", "SWAP_COST_NOT_LOWER",
                        "A troca, incluindo transporte e recomposição, não reduz o custo estimado de mão de obra.",
                        conventional=float(conventional_cost), swap=float(swap_cost),
                        saved=float(saved))
    return decision("SWAP_PALLET", "SWAP_LOWER_LABOUR_COST",
                    "A troca cumpre as condições operacionais e apresenta menor custo estimado de mão de obra.",
                    conventional=float(conventional_cost), swap=float(swap_cost),
                    saved=float(saved))
