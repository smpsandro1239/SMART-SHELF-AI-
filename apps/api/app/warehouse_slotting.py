"""Explainable warehouse slotting recommendations from complete daily sales history.

This module ranks product rotation. It does not choose a physical bin: warehouse
locations, travel distances, dimensions and handling constraints are not yet modeled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping
import math


@dataclass(frozen=True)
class SlottingRecommendation:
    products: tuple[dict[str, Any], ...]
    analysed_products: int
    excluded_incomplete_history: int


def recommend_warehouse_slotting(
    product_sales: Iterable[Mapping[str, Any]],
    *,
    minimum_average_daily_sales: float = 1.0,
) -> SlottingRecommendation:
    """Rank products by average daily sales and flag high-rotation candidates.

    The high-rotation threshold is the greater of the configured minimum and
    the 75th percentile of complete-history products. It is a review signal,
    not an automatic relocation decision.
    """
    if (isinstance(minimum_average_daily_sales, bool)
            or not isinstance(minimum_average_daily_sales, (int, float))
            or not math.isfinite(float(minimum_average_daily_sales))
            or minimum_average_daily_sales < 0):
        raise ValueError("minimum_average_daily_sales must be finite and non-negative")

    complete: list[dict[str, Any]] = []
    excluded = 0
    for source in product_sales:
        row = dict(source)
        days = row.get("history_days")
        expected = row.get("expected_days")
        if (isinstance(days, bool) or not isinstance(days, int)
                or isinstance(expected, bool) or not isinstance(expected, int)
                or expected < 1 or days != expected):
            excluded += 1
            continue
        quantity = row.get("total_quantity")
        if (isinstance(quantity, bool) or not isinstance(quantity, (int, float))
                or not math.isfinite(float(quantity)) or quantity < 0):
            excluded += 1
            continue
        average = float(quantity) / expected
        row["average_daily_sales"] = round(average, 3)
        complete.append(row)

    if not complete:
        return SlottingRecommendation((), 0, excluded)

    ranked_averages = sorted(row["average_daily_sales"] for row in complete)
    percentile_index = max(0, math.ceil(0.75 * len(ranked_averages)) - 1)
    high_threshold = max(float(minimum_average_daily_sales), ranked_averages[percentile_index])

    complete.sort(key=lambda row: (
        -row["average_daily_sales"],
        str(row.get("product_name") or "").casefold(),
        int(row.get("product_id") or 0),
    ))
    for rank, row in enumerate(complete, start=1):
        is_high = row["average_daily_sales"] >= high_threshold and row["average_daily_sales"] >= minimum_average_daily_sales
        row["rotation_rank"] = rank
        row["rotation_threshold_units_per_day"] = round(high_threshold, 3)
        row["rotation_band"] = (
            "HIGH" if is_high else
            "MEDIUM" if row["average_daily_sales"] >= minimum_average_daily_sales else "LOW"
        )
        row["recommendation"] = (
            "CONSIDER_NEAR_PICKING_AREA" if is_high else "KEEP_CURRENT_LOCATION_PENDING_REVIEW"
        )
        row["automatic_relocation_allowed"] = False
        row["explanation"] = (
            f"Média de {row['average_daily_sales']:.3f} unidades/dia em {row['expected_days']} dias completos; "
            "candidato a localização mais próxima da zona de preparação, sujeito a validação de capacidade, "
            "dimensões, peso, segurança e percurso."
            if is_high else
            "A rotação observada não justifica, por si só, prioridade de proximidade."
        )

    return SlottingRecommendation(tuple(complete), len(complete), excluded)
