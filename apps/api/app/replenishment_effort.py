"""Evidence-based elapsed-time estimates for replenishment work queues.

Elapsed time is a proxy, not active labour time: it may include interruptions,
waiting and breaks. Estimates are suppressed until the sample threshold is met.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import fmean
from typing import Any, Iterable, Mapping


_PRIORITY_MAP = {
    "URGENT_REVIEW": "URGENT",
    "HIGH": "HIGH",
    "REVIEW": "NORMAL",
    "RECAPTURE": "NORMAL",
    "NONE": "NORMAL",
}


def enrich_plan_with_effort_estimates(
    recommendations: Iterable[Mapping[str, Any]],
    completed_history: Iterable[Mapping[str, Any]],
    *,
    minimum_sample_size: int = 5,
) -> dict[str, Any]:
    """Annotate candidates using zone+priority, then zone-only benchmarks."""
    if (isinstance(minimum_sample_size, bool)
            or not isinstance(minimum_sample_size, int)
            or not 2 <= minimum_sample_size <= 100):
        raise ValueError("minimum_sample_size must be between 2 and 100")

    by_zone_priority: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_zone: dict[str, list[float]] = defaultdict(list)
    valid_history = 0
    for row in completed_history:
        zone = str(row.get("zone_name") or "Zona não identificada")
        priority = str(row.get("priority") or "NORMAL").upper()
        started = row.get("started_at")
        completed = row.get("completed_at")
        if not isinstance(started, datetime) or not isinstance(completed, datetime):
            continue
        if started.tzinfo is None and completed.tzinfo is not None:
            started = started.replace(tzinfo=completed.tzinfo)
        elif completed.tzinfo is None and started.tzinfo is not None:
            completed = completed.replace(tzinfo=started.tzinfo)
        seconds = (completed - started).total_seconds()
        if seconds <= 0 or seconds > 7 * 24 * 60 * 60:
            continue
        minutes = seconds / 60.0
        by_zone_priority[(zone.casefold(), priority)].append(minutes)
        by_zone[zone.casefold()].append(minutes)
        valid_history += 1

    output: list[dict[str, Any]] = []
    estimated_total = 0.0
    estimated_count = 0
    unestimated_count = 0
    for source in recommendations:
        item = dict(source)
        zone = str(item.get("zone_name") or "Zona não identificada")
        task_priority = _PRIORITY_MAP.get(
            str(item.get("proposed_priority") or "REVIEW").upper(), "NORMAL"
        )
        exact = by_zone_priority.get((zone.casefold(), task_priority), [])
        fallback = by_zone.get(zone.casefold(), [])
        if len(exact) >= minimum_sample_size:
            sample = exact
            basis = "ZONE_AND_PRIORITY_HISTORY"
        elif len(fallback) >= minimum_sample_size:
            sample = fallback
            basis = "ZONE_HISTORY"
        else:
            sample = []
            basis = "INSUFFICIENT_SAMPLE"

        if sample:
            estimate = round(fmean(sample), 2)
            item["estimated_elapsed_minutes"] = estimate
            item["effort_estimate_status"] = "ESTIMATED"
            item["effort_estimate_basis"] = basis
            item["effort_estimate_sample_count"] = len(sample)
            estimated_total += estimate
            estimated_count += 1
        else:
            item["estimated_elapsed_minutes"] = None
            item["effort_estimate_status"] = "UNKNOWN"
            item["effort_estimate_basis"] = basis
            item["effort_estimate_sample_count"] = max(len(exact), len(fallback))
            unestimated_count += 1
        item["effort_metric"] = "ELAPSED_TIME_NOT_ACTIVE_LABOUR"
        output.append(item)

    return {
        "recommendations": output,
        "summary": {
            "historical_valid_samples": valid_history,
            "estimated_candidates": estimated_count,
            "unestimated_candidates": unestimated_count,
            "estimated_total_elapsed_minutes": round(estimated_total, 2),
            "minimum_sample_size": minimum_sample_size,
            "metric": "ELAPSED_TIME_NOT_ACTIVE_LABOUR",
        },
    }
