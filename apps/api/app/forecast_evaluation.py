"""Forecast evaluation metrics for retrospective SMART SHELF AI validation.

Inputs must contain paired predictions and actual observations for the same
store, SKU and time bucket. Missing observations must be omitted, never treated
as zero. Metrics are descriptive and do not authorize stock movements.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Any


@dataclass(frozen=True)
class ForecastObservation:
    actual: float
    predicted: float
    store_id: str | int | None = None
    product_id: str | int | None = None
    period: str | None = None


@dataclass(frozen=True)
class ForecastEvaluation:
    status: str
    observations: int
    mae: float | None
    rmse: float | None
    wape: float | None
    bias: float | None
    mape: float | None
    zero_actual_observations: int
    by_store: tuple[dict[str, Any], ...]
    by_product: tuple[dict[str, Any], ...]


def _quantity(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric, not boolean")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return result


def _metrics(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    if not pairs:
        return {
            "observations": 0,
            "mae": None,
            "rmse": None,
            "wape": None,
            "bias": None,
            "mape": None,
            "zero_actual_observations": 0,
        }

    errors = [predicted - actual for actual, predicted in pairs]
    absolute_errors = [abs(error) for error in errors]
    actual_total = sum(actual for actual, _ in pairs)
    absolute_actual_total = sum(abs(actual) for actual, _ in pairs)
    nonzero_pairs = [
        (actual, predicted)
        for actual, predicted in pairs
        if actual != 0
    ]
    return {
        "observations": len(pairs),
        "mae": round(sum(absolute_errors) / len(pairs), 4),
        "rmse": round(math.sqrt(sum(error * error for error in errors) / len(pairs)), 4),
        "wape": (
            round(sum(absolute_errors) / absolute_actual_total, 4)
            if absolute_actual_total > 0 else None
        ),
        "bias": round(sum(errors) / len(pairs), 4),
        "mape": (
            round(
                sum(abs(predicted - actual) / abs(actual) for actual, predicted in nonzero_pairs)
                / len(nonzero_pairs),
                4,
            )
            if nonzero_pairs else None
        ),
        "zero_actual_observations": len(pairs) - len(nonzero_pairs),
    }


def _group_metrics(
    rows: list[ForecastObservation],
    attribute: str,
) -> tuple[dict[str, Any], ...]:
    groups: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        value = getattr(row, attribute)
        if value is not None:
            groups[str(value)].append((row.actual, row.predicted))
    return tuple(
        {"key": key, **_metrics(groups[key])}
        for key in sorted(groups)
    )


def evaluate_forecasts(
    observations: Iterable[ForecastObservation | Mapping[str, Any]],
    *,
    minimum_observations: int = 1,
) -> ForecastEvaluation:
    """Evaluate paired forecasts using MAE, RMSE, WAPE, bias and MAPE.

    MAPE excludes zero-actual rows and reports their count separately.
    WAPE is undefined when the total actual demand is zero. Positive bias
    means systematic over-forecasting; negative bias means under-forecasting.
    """
    if (
        isinstance(minimum_observations, bool)
        or not isinstance(minimum_observations, int)
        or minimum_observations < 1
    ):
        raise ValueError("minimum_observations must be a positive integer")

    rows: list[ForecastObservation] = []
    for index, item in enumerate(observations):
        if isinstance(item, ForecastObservation):
            actual_value = item.actual
            predicted_value = item.predicted
            store_id = item.store_id
            product_id = item.product_id
            period = item.period
        elif isinstance(item, Mapping):
            if "actual" not in item or "predicted" not in item:
                raise ValueError(f"observation[{index}] requires actual and predicted")
            actual_value = item["actual"]
            predicted_value = item["predicted"]
            store_id = item.get("store_id")
            product_id = item.get("product_id")
            period = item.get("period")
        else:
            raise ValueError(f"observation[{index}] has an unsupported type")

        rows.append(ForecastObservation(
            actual=_quantity(actual_value, f"observation[{index}].actual"),
            predicted=_quantity(predicted_value, f"observation[{index}].predicted"),
            store_id=store_id,
            product_id=product_id,
            period=period,
        ))

    metrics = _metrics([(row.actual, row.predicted) for row in rows])
    status = "AVAILABLE" if len(rows) >= minimum_observations else "INSUFFICIENT_HISTORY"
    return ForecastEvaluation(
        status=status,
        observations=metrics["observations"],
        mae=metrics["mae"],
        rmse=metrics["rmse"],
        wape=metrics["wape"],
        bias=metrics["bias"],
        mape=metrics["mape"],
        zero_actual_observations=metrics["zero_actual_observations"],
        by_store=_group_metrics(rows, "store_id"),
        by_product=_group_metrics(rows, "product_id"),
    )
