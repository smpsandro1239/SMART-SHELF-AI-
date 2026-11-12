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


@dataclass(frozen=True)
class PhysicalSlottingResult:
    status: str
    product_id: int
    candidates: tuple[dict[str, Any], ...]
    rejected_locations: tuple[dict[str, Any], ...]


def recommend_physical_slot(
    *,
    product_id: int,
    required_quantity: float,
    product_profile: Mapping[str, Any] | None,
    locations: Iterable[Mapping[str, Any]],
) -> PhysicalSlottingResult:
    """Rank physically feasible bins; never performs a stock movement.

    Each location must provide capacity, distance, temperature and current
    occupancy (occupied_volume_cm3 / occupied_weight_kg). If segregation is
    required, a location containing another SKU is rejected.
    """
    if isinstance(product_id, bool) or not isinstance(product_id, int) or product_id <= 0:
        raise ValueError("product_id must be a positive integer")
    if (isinstance(required_quantity, bool)
            or not isinstance(required_quantity, (int, float))
            or not math.isfinite(float(required_quantity))
            or required_quantity <= 0):
        raise ValueError("required_quantity must be finite and positive")
    if not product_profile:
        return PhysicalSlottingResult("PRODUCT_PROFILE_REQUIRED", product_id, (), ())

    def positive_number(value: Any) -> bool:
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and math.isfinite(float(value)) and value > 0)

    unit_volume = product_profile.get("unit_volume_cm3")
    unit_weight = product_profile.get("unit_weight_kg")
    if not positive_number(unit_volume) or not positive_number(unit_weight):
        return PhysicalSlottingResult("INVALID_PRODUCT_PROFILE", product_id, (), ())

    temperature = product_profile.get("temperature_requirement", "AMBIENT")
    if temperature not in {"AMBIENT", "CHILLED", "FROZEN"}:
        return PhysicalSlottingResult("INVALID_PRODUCT_PROFILE", product_id, (), ())

    required_volume = float(unit_volume) * float(required_quantity)
    required_weight = float(unit_weight) * float(required_quantity)
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for location in locations:
        loc = dict(location)
        code = str(loc.get("code") or loc.get("location_id") or "UNKNOWN")
        reason = None
        distance = loc.get("distance_to_picking_m")
        max_volume = loc.get("max_volume_cm3")
        max_weight = loc.get("max_weight_kg")
        occupied_volume = loc.get("occupied_volume_cm3", 0)
        occupied_weight = loc.get("occupied_weight_kg", 0)

        if not loc.get("is_active", True):
            reason = "LOCATION_INACTIVE"
        elif loc.get("temperature_zone") != temperature:
            reason = "TEMPERATURE_INCOMPATIBLE"
        elif not positive_number(max_volume) or not positive_number(max_weight):
            reason = "INVALID_LOCATION_CAPACITY"
        elif (isinstance(distance, bool) or not isinstance(distance, (int, float))
              or not math.isfinite(float(distance)) or distance < 0):
            reason = "INVALID_PICKING_DISTANCE"
        elif occupied_volume is None or occupied_weight is None:
            reason = "UNKNOWN_CURRENT_OCCUPANCY"
        elif (isinstance(occupied_volume, bool) or not isinstance(occupied_volume, (int, float))
              or not math.isfinite(float(occupied_volume)) or occupied_volume < 0
              or isinstance(occupied_weight, bool) or not isinstance(occupied_weight, (int, float))
              or not math.isfinite(float(occupied_weight)) or occupied_weight < 0):
            reason = "INVALID_CURRENT_OCCUPANCY"
        elif required_volume > float(max_volume) - float(occupied_volume):
            reason = "INSUFFICIENT_VOLUME_CAPACITY"
        elif required_weight > float(max_weight) - float(occupied_weight):
            reason = "INSUFFICIENT_WEIGHT_CAPACITY"
        elif product_profile.get("requires_segregation") and loc.get("other_product_count", 0) > 0:
            reason = "SEGREGATION_REQUIRED"

        if reason:
            rejected.append({"location_code": code, "reason": reason})
            continue

        remaining_volume = float(max_volume) - float(occupied_volume)
        remaining_weight = float(max_weight) - float(occupied_weight)
        volume_utilization = (float(occupied_volume) + required_volume) / float(max_volume)
        weight_utilization = (float(occupied_weight) + required_weight) / float(max_weight)
        utilization = max(volume_utilization, weight_utilization)
        candidates.append({
            "location_id": loc.get("location_id"),
            "location_code": code,
            "distance_to_picking_m": round(float(distance), 2),
            "required_volume_cm3": round(required_volume, 2),
            "required_weight_kg": round(required_weight, 3),
            "remaining_volume_after_placement_cm3": round(remaining_volume - required_volume, 2),
            "remaining_weight_after_placement_kg": round(remaining_weight - required_weight, 3),
            "projected_capacity_utilization": round(utilization, 4),
            "fragile_handling_review_required": bool(product_profile.get("is_fragile")),
            "automatic_movement_allowed": False,
        })

    candidates.sort(key=lambda item: (
        item["distance_to_picking_m"],
        item["projected_capacity_utilization"],
        item["location_code"].casefold(),
    ))
    status = "CANDIDATES_FOUND" if candidates else "NO_COMPATIBLE_LOCATION"
    return PhysicalSlottingResult(status, product_id, tuple(candidates), tuple(rejected))
