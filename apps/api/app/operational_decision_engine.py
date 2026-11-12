"""Evidence-based operational decision engine for shelf availability.

This module deliberately accepts normalized evidence instead of reading from a
database or calling external systems. It never treats missing data as zero,
never creates stock movements, and suppresses duplicate work when an active
task already exists.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from typing import Any, Iterable


ACTIVE_TASK_STATUSES = {"PENDING", "ASSIGNED", "IN_PROGRESS"}
ATTENTION_OBSERVATION_STATUSES = {"LOW_STOCK", "EMPTY", "MISPLACED", "DAMAGED"}


@dataclass(frozen=True)
class DecisionPolicy:
    observation_max_age_minutes: int = 180
    inventory_max_age_minutes: int = 360
    demand_horizon_hours: int = 24
    minimum_confidence: float = 0.55
    low_stock_coverage_hours: float = 12.0

    def validate(self) -> None:
        for name in ("observation_max_age_minutes", "inventory_max_age_minutes",
                     "demand_horizon_hours"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("minimum_confidence",):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        value = self.low_stock_coverage_hours
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("low_stock_coverage_hours must be positive")


def _parse_timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    else:
        raise ValueError(f"{field} must be a datetime or ISO-8601 string")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return result.astimezone(timezone.utc)


def _finite_nonnegative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return number


def _age_minutes(timestamp: datetime, now: datetime) -> float:
    return (now - timestamp).total_seconds() / 60.0


def evaluate_shelf_decision(
    *,
    now: datetime,
    observation: dict[str, Any] | None,
    inventory: dict[str, Any] | None,
    demand_forecast: dict[str, Any] | None = None,
    active_tasks: Iterable[dict[str, Any]] = (),
    policy: DecisionPolicy | None = None,
) -> dict[str, Any]:
    """Return an explainable decision for one product/shelf pair.

    Expected observation keys: status, observed_at, confidence, source.
    Expected inventory keys: available_quantity, recorded_at.
    Expected forecast keys: predicted_units, horizon_hours, generated_at.
    """
    selected_policy = policy or DecisionPolicy()
    selected_policy.validate()
    current = _parse_timestamp(now, "now")
    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []

    observation_status = "UNKNOWN"
    observation_fresh = False
    observation_confidence: float | None = None
    if observation is not None:
        observation_status = str(observation.get("status", "UNKNOWN")).upper()
        observed_at = _parse_timestamp(observation.get("observed_at"), "observation.observed_at")
        age = _age_minutes(observed_at, current)
        raw_confidence = observation.get("confidence")
        if raw_confidence is not None:
            observation_confidence = _finite_nonnegative(raw_confidence, "observation.confidence")
            if observation_confidence > 1:
                raise ValueError("observation.confidence cannot exceed 1")
        observation_fresh = 0 <= age <= selected_policy.observation_max_age_minutes
        evidence.append({
            "type": "SHELF_OBSERVATION", "status": observation_status,
            "source": str(observation.get("source") or "unspecified"),
            "observed_at": observed_at.isoformat(), "age_minutes": round(age, 2),
            "fresh": observation_fresh, "confidence": observation_confidence,
        })
        if age < 0:
            warnings.append("A observação da prateleira tem timestamp no futuro e foi ignorada.")
        elif not observation_fresh:
            warnings.append("A observação da prateleira está desatualizada.")
        if observation_confidence is None or observation_confidence < selected_policy.minimum_confidence:
            warnings.append("A confiança da observação é insuficiente para uma decisão automática.")

    inventory_quantity: float | None = None
    inventory_fresh = False
    if inventory is not None:
        inventory_quantity = _finite_nonnegative(inventory.get("available_quantity"), "inventory.available_quantity")
        recorded_at = _parse_timestamp(inventory.get("recorded_at"), "inventory.recorded_at")
        age = _age_minutes(recorded_at, current)
        inventory_fresh = 0 <= age <= selected_policy.inventory_max_age_minutes
        evidence.append({
            "type": "INVENTORY_SNAPSHOT", "available_quantity": inventory_quantity,
            "recorded_at": recorded_at.isoformat(), "age_minutes": round(age, 2),
            "fresh": inventory_fresh,
        })
        if age < 0:
            warnings.append("O snapshot de inventário tem timestamp no futuro e foi ignorado.")
        elif not inventory_fresh:
            warnings.append("O snapshot de inventário está desatualizado.")

    forecast_quantity: float | None = None
    forecast_hours: float | None = None
    forecast_fresh = False
    if demand_forecast is not None:
        forecast_quantity = _finite_nonnegative(demand_forecast.get("predicted_units"), "demand_forecast.predicted_units")
        forecast_hours = _finite_nonnegative(demand_forecast.get("horizon_hours"), "demand_forecast.horizon_hours")
        if forecast_hours <= 0:
            raise ValueError("demand_forecast.horizon_hours must be positive")
        generated_at = _parse_timestamp(demand_forecast.get("generated_at"), "demand_forecast.generated_at")
        age = _age_minutes(generated_at, current)
        forecast_fresh = 0 <= age <= selected_policy.demand_horizon_hours * 60
        evidence.append({
            "type": "DEMAND_FORECAST", "predicted_units": forecast_quantity,
            "horizon_hours": forecast_hours, "generated_at": generated_at.isoformat(),
            "age_minutes": round(age, 2), "fresh": forecast_fresh,
            "method": str(demand_forecast.get("method") or "UNSPECIFIED"),
            "source_records": demand_forecast.get("source_records"),
            "observed_sales_days": demand_forecast.get("observed_sales_days"),
        })
        if age < 0:
            warnings.append("A previsão de procura tem timestamp no futuro e foi ignorada.")
        elif not forecast_fresh:
            warnings.append("A previsão de procura está desatualizada.")

    tasks = list(active_tasks)
    active = [task for task in tasks if str(task.get("status", "")).upper() in ACTIVE_TASK_STATUSES]
    if active:
        evidence.append({"type": "ACTIVE_TASKS", "count": len(active),
                         "task_ids": [task.get("id") for task in active]})

    reliable_visual_signal = (
        observation is not None and observation_fresh
        and observation_confidence is not None
        and observation_confidence >= selected_policy.minimum_confidence
    )
    visual_attention = reliable_visual_signal and observation_status in ATTENTION_OBSERVATION_STATUSES
    demand_rate_per_hour = (
        forecast_quantity / forecast_hours
        if forecast_quantity is not None and forecast_hours is not None and forecast_hours > 0
        else None
    )
    inventory_coverage_hours = None
    if inventory_quantity is not None and demand_rate_per_hour is not None and demand_rate_per_hour > 0:
        inventory_coverage_hours = inventory_quantity / demand_rate_per_hour

    projected_shortage = (
        inventory is not None and inventory_fresh
        and demand_forecast is not None and forecast_fresh
        and forecast_hours is not None and forecast_hours <= selected_policy.demand_horizon_hours
        and inventory_coverage_hours is not None
        and inventory_coverage_hours <= selected_policy.low_stock_coverage_hours
    )

    if active:
        status = "ALREADY_IN_PROGRESS"
        priority = "NONE"
        reason = "Já existe uma tarefa operacional ativa para este produto/localização."
    elif visual_attention or projected_shortage:
        status = "ACTION_RECOMMENDED"
        priority = "HIGH" if observation_status == "EMPTY" or (inventory_quantity == 0 and inventory_fresh) else "NORMAL"
        reason_parts = []
        if visual_attention:
            reason_parts.append(f"observação fiável indica {observation_status.lower()}")
        if projected_shortage:
            reason_parts.append("inventário disponível não cobre a procura prevista no horizonte")
        reason = "; ".join(reason_parts) + "."
    elif observation is None and inventory is None:
        status = "INSUFFICIENT_EVIDENCE"
        priority = "NONE"
        reason = "Não existem observações nem inventário para avaliar a disponibilidade."
    else:
        status = "MONITOR"
        priority = "NONE"
        reason = "A evidência disponível não justifica criar uma tarefa neste momento."

    quantity_to_replenish: float | None = None
    if status == "ACTION_RECOMMENDED":
        if inventory is None or not inventory_fresh:
            warnings.append("Quantidade a repor não calculada: falta inventário recente.")
        elif forecast_quantity is None or not forecast_fresh:
            warnings.append("Quantidade a repor não calculada: falta previsão recente.")
        else:
            quantity_to_replenish = round(max(0.0, forecast_quantity - inventory_quantity), 3)

    return {
        "status": status,
        "priority": priority,
        "reason": reason,
        "suggested_replenishment_quantity": quantity_to_replenish,
        "inventory_coverage_hours": (
            round(inventory_coverage_hours, 2) if inventory_coverage_hours is not None else None
        ),
        "automatic_stock_movement_allowed": False,
        "requires_human_approval": status == "ACTION_RECOMMENDED",
        "evidence": evidence,
        "warnings": list(dict.fromkeys(warnings)),
        "policy": asdict(selected_policy),
        "evaluated_at": current.isoformat(),
    }
