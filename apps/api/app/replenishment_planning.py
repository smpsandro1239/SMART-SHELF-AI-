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

    groups = tuple(
        PlannedZone(zone_id=key[0], zone_name=key[1], items=tuple(items))
        for key, items in sorted(
            grouped.items(), key=lambda pair: (pair[0][1].casefold(), pair[0][0] or 0)
        )
    )
    return ReplenishmentPlan(
        groups=groups,
        total_candidates=len(candidates),
        returned_candidates=len(selected),
        excluded=excluded,
    )
