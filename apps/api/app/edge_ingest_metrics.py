"""Process-local, privacy-safe counters for the authenticated Edge HTTP boundary."""
from __future__ import annotations
import logging
import threading
from collections import Counter

logger = logging.getLogger("smart_shelf.edge_ingest_metrics")
_lock = threading.Lock()
_counts: Counter[str] = Counter()
_ALLOWED = frozenset({
    "events_received", "events_accepted", "events_duplicate", "events_rejected",
    "authentication_rejected", "authorization_rejected", "contract_rejected",
    "request_replay_rejected", "sequence_conflicts", "event_id_conflicts",
})

def record_edge_ingest_outcome(outcome: str) -> None:
    if outcome not in _ALLOWED:
        return
    with _lock:
        _counts[outcome] += 1
        snapshot = dict(_counts)
    logger.info("edge_ingest_metric outcome=%s counters=%s", outcome, snapshot)

def edge_ingest_metrics_snapshot() -> dict[str, int]:
    with _lock:
        return {name: _counts.get(name, 0) for name in sorted(_ALLOWED)}

def reset_edge_ingest_metrics() -> None:
    with _lock:
        _counts.clear()
