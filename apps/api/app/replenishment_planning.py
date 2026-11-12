"""Read-only prioritisation and zone grouping for shelf replenishment work.

Priority labels are operational heuristics, not calibrated probabilities. This
module never creates tasks, allocates employees, or changes inventory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any


@dataclass(frozen=True)
class PlannedZone:
    zone_id: int | None
    zone_name: str
    items: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ReplenishmentPlan:
    groups: tuple[PlannedZone, ...]
    total_candidates: int
    returned_candidates: int
    excluded: dict[str, int]


_PRIORITY = {
    "NEEDS_REPLENISHMENT": ("HIGH", 0),
    "BACKROOM_OUT_OF_STOCK": ("URGENT_REVIEW", 1),
    "INVENTORY_UNKNOWN": ("REVIEW", 2),
    "LOW_CONFIDENCE": ("REVIEW", 3),
    "STALE_OBSERVATION": ("RECAPTURE", 4),
    "NO_ACTION": ("NONE", 5),
}


def build_replenishment_plan(
    recommendations: Iterable[Mapping[str, Any]],
    *,
    active_keys: set[tuple[int, int]] | None = None,
    limit: int = 200,
) -> ReplenishmentPlan:
    """Rank recommendation rows and group them by zone without mutating input."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    active_keys = active_keys or set()
    candidates: list[dict[str, Any]] = []
    excluded = {"NO_ACTION": 0, "ACTIVE_TASK_EXISTS": 0}
    for source in recommendations:
        item = dict(source)
        status = str(item.get("recommendation_status") or "INVENTORY_UNKNOWN")
        if status == "NO_ACTION":
            excluded["NO_ACTION"] += 1
            continue
        key = (item.get("shelf_id"), item.get("product_id"))
        if key in active_keys:
            excluded["ACTIVE_TASK_EXISTS"] += 1
            continue

        priority, rank = _PRIORITY.get(status, ("REVIEW", 2))
        item["proposed_priority"] = priority
        item["priority_rank"] = rank
        item["task_creation_allowed"] = (
            status == "NEEDS_REPLENISHMENT"
            and isinstance(item.get("suggested_quantity"), (int, float))
            and not isinstance(item.get("suggested_quantity"), bool)
            and item["suggested_quantity"] > 0
        )
        if not item["task_creation_allowed"]:
            item["proposed_priority"] = "RECAPTURE" if status == "STALE_OBSERVATION" else "REVIEW"
            item["priority_rank"] = 4 if status == "STALE_OBSERVATION" else 2
        candidates.append(item)

    candidates.sort(key=lambda row: (
        row["priority_rank"],
        str(row.get("zone_name") or "").casefold(),
        str(row.get("shelf_code") or "").casefold(),
        str(row.get("product_name") or "").casefold(),
        int(row.get("shelf_id") or 0),
        int(row.get("product_id") or 0),
    ))
    selected = candidates[:limit]
    grouped: dict[tuple[int | None, str], list[dict[str, Any]]] = {}
    for item in selected:
        key = (item.get("zone_id"), str(item.get("zone_name") or "Zona não identificada"))
        grouped.setdefault(key, []).append(item)

    groups_list: list[PlannedZone] = []
    for key, zone_items in sorted(
        grouped.items(), key=lambda pair: (pair[0][1].casefold(), pair[0][0] or 0)
    ):
        # No shelf coordinates or aisle graph exist yet. Use a stable, transparent
        # shelf-code/position ordering and label it as a suggested sequence only.
        route_sorted_items = sorted(
            zone_items,
            key=lambda row: (
                str(row.get("shelf_code") or "").casefold(),
                str(row.get("position") or "").casefold(),
                int(row.get("shelf_id") or 0),
                int(row.get("product_id") or 0),
            ),
        )
        route_order_by_shelf: dict[str, int] = {}
        for item in route_sorted_items:
            shelf_id = int(item.get("shelf_id") or 0)
            route_key = str(item.get("shelf_code") or f"#{shelf_id}").casefold()
            if route_key not in route_order_by_shelf:
                route_order_by_shelf[route_key] = len(route_order_by_shelf) + 1

        # Present work by operational priority; route_order remains an independent shelf hint.
        ordered_items = sorted(
            zone_items,
            key=lambda row: (
                row["priority_rank"],
                str(row.get("shelf_code") or "").casefold(),
                str(row.get("position") or "").casefold(),
                int(row.get("shelf_id") or 0),
                int(row.get("product_id") or 0),
            ),
        )
        for item in ordered_items:
            shelf_id = int(item.get("shelf_id") or 0)
            route_key = str(item.get("shelf_code") or f"#{shelf_id}").casefold()
            item["route_order"] = route_order_by_shelf[route_key]
            item["route_basis"] = "ZONE_THEN_SHELF_CODE_AND_POSITION"
            item["physical_route_optimized"] = False
        groups_list.append(PlannedZone(
            zone_id=key[0], zone_name=key[1], items=tuple(ordered_items)
        ))
    groups = tuple(groups_list)
    return ReplenishmentPlan(
        groups=groups,
        total_candidates=len(candidates),
        returned_candidates=len(selected),
        excluded=excluded,
    )
