"""Temporal consensus for repeated shelf observations.

The caller must scope observations to one store/shelf/SKU before invoking this
module. This module is deliberately pure: it does not persist alerts or create
replenishment tasks.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Iterable


ATTENTION_STATUSES = frozenset({"LOW_STOCK", "EMPTY", "MISPLACED", "DAMAGED"})


def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError("confidence must be finite and between 0 and 1")
    return result


def evaluate_observation_consensus(
    observations: Iterable[dict[str, Any]],
    *,
    now: datetime,
    window_minutes: int = 15,
    minimum_confirmations: int = 3,
    minimum_interval_seconds: int = 10,
    minimum_confidence: float = 0.65,
) -> dict[str, Any]:
    """Evaluate repeated evidence for one already-scoped shelf/SKU pair.

    Future-dated, stale, low-confidence and non-attention observations are not
    counted. Confirmations of the same status must be separated by the minimum
    interval, reducing frame-burst inflation. Competing confirmed statuses
    return CONFLICT rather than selecting an arbitrary winner.
    """
    current = _timestamp(now, "now")
    for name, value, minimum, maximum in (
        ("window_minutes", window_minutes, 1, 1440),
        ("minimum_confirmations", minimum_confirmations, 2, 100),
        ("minimum_interval_seconds", minimum_interval_seconds, 0, 3600),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    threshold = _confidence(minimum_confidence)
    cutoff = current - timedelta(minutes=window_minutes)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ignored = {"future": 0, "stale": 0, "low_confidence": 0, "irrelevant": 0}
    for index, item in enumerate(observations):
        if not isinstance(item, dict):
            raise ValueError("each observation must be a dictionary")
        status = str(item.get("status", "")).strip().upper()
        if status not in ATTENTION_STATUSES:
            ignored["irrelevant"] += 1
            continue
        observed_at = _timestamp(item.get("observed_at"), f"observations[{index}].observed_at")
        if observed_at > current:
            ignored["future"] += 1
            continue
        if observed_at < cutoff:
            ignored["stale"] += 1
            continue
        confidence = _confidence(item.get("confidence"))
        if confidence < threshold:
            ignored["low_confidence"] += 1
            continue
        grouped[status].append({
            "observed_at": observed_at,
            "confidence": confidence,
            "source": str(item.get("source") or "unspecified"),
        })

    confirmed: dict[str, list[dict[str, Any]]] = {}
    for status, entries in grouped.items():
        accepted: list[dict[str, Any]] = []
        for entry in sorted(entries, key=lambda row: row["observed_at"]):
            if not accepted or (
                entry["observed_at"] - accepted[-1]["observed_at"]
            ).total_seconds() >= minimum_interval_seconds:
                accepted.append(entry)
        if len(accepted) >= minimum_confirmations:
            confirmed[status] = accepted

    ranked = sorted(confirmed.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    if not ranked:
        result_status = "NO_CONSENSUS"
        selected_status = None
        selected = []
    elif len(ranked) > 1 and len(ranked[0][1]) == len(ranked[1][1]):
        result_status = "CONFLICT"
        selected_status = None
        selected = []
    elif len(ranked) > 1 and len(ranked[1][1]) >= minimum_confirmations:
        result_status = "CONFLICT"
        selected_status = None
        selected = []
    else:
        result_status = "CONFIRMED"
        selected_status, selected = ranked[0]

    if selected:
        first_seen = selected[0]["observed_at"]
        last_seen = selected[-1]["observed_at"]
        average_confidence = round(sum(row["confidence"] for row in selected) / len(selected), 4)
        sources = sorted({row["source"] for row in selected})
        count = len(selected)
    else:
        first_seen = last_seen = None
        average_confidence = None
        sources = []
        count = 0

    return {
        "status": result_status,
        "consensus_observation_status": selected_status,
        "confirmations": count,
        "required_confirmations": minimum_confirmations,
        "first_seen_at": first_seen.isoformat() if first_seen else None,
        "last_seen_at": last_seen.isoformat() if last_seen else None,
        "average_confidence": average_confidence,
        "sources": sources,
        "window_minutes": window_minutes,
        "minimum_interval_seconds": minimum_interval_seconds,
        "ignored_observations": ignored,
        "requires_human_approval": True,
        "automatic_task_creation_allowed": False,
        "automatic_stock_movement_allowed": False,
    }
