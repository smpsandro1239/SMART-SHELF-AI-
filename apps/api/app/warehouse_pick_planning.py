"""Read-only warehouse pick proposals for shelf replenishment.

Allocations are advisory only. They do not reserve stock, mutate placements,
create tasks, or issue warehouse movements.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable, Mapping


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def build_warehouse_pick_plan(
    candidates: Iterable[Mapping[str, Any]],
    placements: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Aggregate demand per SKU and propose compatible stock locations.

    Product temperature profile is mandatory. A missing profile or missing
    quantity is surfaced as unknown instead of silently assuming ambient stock.
    """
    demand: dict[int, float] = defaultdict(float)
    product_profile: dict[int, str | None] = {}
    product_candidate_count: dict[int, int] = defaultdict(int)
    candidate_results: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()

    for candidate in candidates:
        item = dict(candidate)
        product_id = item.get("product_id")
        shelf_id = item.get("shelf_id")
        if (isinstance(product_id, bool) or not isinstance(product_id, int)
                or isinstance(shelf_id, bool) or not isinstance(shelf_id, int)):
            continue
        key = (shelf_id, product_id)
        if key in seen:
            continue
        seen.add(key)
        quantity = _number(item.get("suggested_quantity"))
        allowed = item.get("task_creation_allowed") is True
        profile = item.get("temperature_requirement")
        profile = str(profile).upper() if profile is not None else None
        if profile not in {"AMBIENT", "CHILLED", "FROZEN"}:
            profile = None
        if allowed and quantity is not None and quantity > 0:
            demand[product_id] += quantity
            product_candidate_count[product_id] += 1
            if product_id not in product_profile:
                product_profile[product_id] = profile
            elif product_profile[product_id] != profile:
                product_profile[product_id] = None
        item["warehouse_pick_status"] = (
            "PENDING_AGGREGATION" if allowed and quantity is not None and quantity > 0
            else "NO_QUANTIFIED_DEMAND"
        )
        candidate_results.append(item)

    eligible: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in placements:
        product_id = row.get("product_id")
        if isinstance(product_id, bool) or not isinstance(product_id, int):
            continue
        quantity = _number(row.get("quantity"))
        distance = _number(row.get("distance_to_picking_m"))
        if quantity is None or quantity <= 0 or distance is None:
            continue
        if row.get("is_active", True) is not True:
            continue
        temperature = str(row.get("temperature_zone") or "").upper()
        eligible[product_id].append({
            **dict(row),
            "quantity": quantity,
            "distance_to_picking_m": distance,
            "temperature_zone": temperature,
        })

    allocations: list[dict[str, Any]] = []
    product_results: list[dict[str, Any]] = []
    for product_id in sorted(demand):
        required = demand[product_id]
        required_temperature = product_profile.get(product_id)
        if required_temperature is None:
            product_results.append({
                "product_id": product_id,
                "required_quantity": round(required, 3),
                "allocated_quantity": 0.0,
                "shortfall_quantity": round(required, 3),
                "status": "PROFILE_UNKNOWN",
                "temperature_requirement": None,
                "candidate_count": product_candidate_count[product_id],
            })
            continue

        remaining = required
        compatible = [
            row for row in eligible.get(product_id, [])
            if row["temperature_zone"] == required_temperature
        ]
        compatible.sort(key=lambda row: (
            row["distance_to_picking_m"],
            str(row.get("aisle") or "").casefold(),
            str(row.get("rack") or "").casefold(),
            str(row.get("bin_code") or "").casefold(),
            str(row.get("location_code") or "").casefold(),
            int(row.get("location_id") or 0),
        ))
        allocated = 0.0
        for location in compatible:
            if remaining <= 0:
                break
            picked = min(remaining, location["quantity"])
            if picked <= 0:
                continue
            allocations.append({
                "product_id": product_id,
                "location_id": location.get("location_id"),
                "location_code": location.get("location_code"),
                "aisle": location.get("aisle"),
                "rack": location.get("rack"),
                "bin_code": location.get("bin_code"),
                "temperature_zone": location["temperature_zone"],
                "distance_to_picking_m": location["distance_to_picking_m"],
                "available_quantity_at_snapshot": location["quantity"],
                "proposed_pick_quantity": round(picked, 3),
            })
            allocated += picked
            remaining -= picked

        shortfall = max(0.0, remaining)
        product_results.append({
            "product_id": product_id,
            "required_quantity": round(required, 3),
            "allocated_quantity": round(allocated, 3),
            "shortfall_quantity": round(shortfall, 3),
            "status": "READY_FOR_REVIEW" if shortfall <= 1e-9 else (
                "PARTIAL_STOCK" if allocated > 0 else "NO_COMPATIBLE_STOCK"
            ),
            "temperature_requirement": required_temperature,
            "candidate_count": product_candidate_count[product_id],
        })

    by_location: dict[tuple[Any, Any], dict[str, Any]] = {}
    for allocation in allocations:
        key = (allocation["location_id"], allocation["location_code"])
        stop = by_location.setdefault(key, {
            "location_id": allocation["location_id"],
            "location_code": allocation["location_code"],
            "aisle": allocation["aisle"],
            "rack": allocation["rack"],
            "bin_code": allocation["bin_code"],
            "distance_to_picking_m": allocation["distance_to_picking_m"],
            "items": [],
        })
        stop["items"].append({
            "product_id": allocation["product_id"],
            "proposed_pick_quantity": allocation["proposed_pick_quantity"],
        })
    stops = sorted(
        by_location.values(),
        key=lambda row: (
            row["distance_to_picking_m"],
            str(row.get("aisle") or "").casefold(),
            str(row.get("rack") or "").casefold(),
            str(row.get("bin_code") or "").casefold(),
        ),
    )
    for index, stop in enumerate(stops, start=1):
        stop["sequence"] = index

    ready = sum(row["status"] == "READY_FOR_REVIEW" for row in product_results)
    partial = sum(row["status"] == "PARTIAL_STOCK" for row in product_results)
    blocked = len(product_results) - ready - partial
    return {
        "status": "READY_FOR_REVIEW" if product_results and blocked == 0 and partial == 0
                  else "PARTIAL_OR_BLOCKED" if product_results else "NO_QUANTIFIED_DEMAND",
        "read_only": True,
        "stock_reserved": False,
        "stock_movement_allowed": False,
        "route_basis": "NEAREST_PICKING_POINT_THEN_AISLE_RACK_BIN",
        "physical_route_optimized": False,
        "distance_metric": "DISTANCE_TO_PICKING_POINT_NOT_INTER_LOCATION_DISTANCE",
        "products": product_results,
        "allocations": allocations,
        "stops": stops,
        "summary": {
            "products_with_demand": len(product_results),
            "ready_for_review": ready,
            "partial_stock": partial,
            "blocked": blocked,
            "proposed_pick_lines": len(allocations),
            "warehouse_stops": len(stops),
            "total_proposed_units": round(sum(row["proposed_pick_quantity"] for row in allocations), 3),
            "total_shortfall_units": round(sum(row["shortfall_quantity"] for row in product_results), 3),
        },
        "candidates_without_quantified_demand": sum(
            row["warehouse_pick_status"] == "NO_QUANTIFIED_DEMAND" for row in candidate_results
        ),
    }
