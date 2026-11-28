"""Independent, idempotent Edge observability aggregation and retention worker.

Only durable authenticated inbox events are used as a source. This process never
mutates inbox, processing, ACK, review, task, or inventory records.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import SessionLocal
from app import models

logger = logging.getLogger("smart_shelf.edge_observability")

INTERVALS = {"15m": timedelta(minutes=15), "daily": timedelta(days=1)}
OVERLAP_WINDOWS = {"15m": 4, "daily": 2}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _database_utc(value: datetime) -> datetime:
    """Normalize DB-returned timestamps; SQLite drops timezone metadata."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def floor_window(value: datetime, interval: timedelta) -> datetime:
    value = _database_utc(value)
    seconds = int(interval.total_seconds())
    epoch = int(value.timestamp())
    return datetime.fromtimestamp((epoch // seconds) * seconds, tz=timezone.utc)


def _dialect_insert(db, table):
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        return pg_insert(table)
    if dialect == "sqlite":
        return sqlite_insert(table)
    raise RuntimeError(f"Unsupported observability database dialect: {dialect}")


def _write_aggregate(db, *, store_id: int, granularity: str, window_start: datetime,
                     dimension: str, count: int, updated_at: datetime) -> None:
    table = models.EdgeObservabilityAggregate.__table__
    statement = _dialect_insert(db, table).values(
        store_id=store_id, granularity=granularity, window_start=window_start,
        metric_name="events_received", dimension_value=dimension,
        value_count=count, updated_at=updated_at,
    )
    statement = statement.on_conflict_do_update(
        index_elements=["store_id", "granularity", "window_start", "metric_name", "dimension_value"],
        set_={"value_count": statement.excluded.value_count, "updated_at": updated_at},
    )
    db.execute(statement)


def _aggregate_window(db, granularity: str, window_start: datetime, window_end: datetime,
                      updated_at: datetime) -> int:
    rows = db.execute(
        select(
            models.EdgeDeviceEventInbox.store_id,
            models.EdgeDeviceEventInbox.event_type,
            func.count(models.EdgeDeviceEventInbox.id),
        )
        .where(
            models.EdgeDeviceEventInbox.received_at >= window_start,
            models.EdgeDeviceEventInbox.received_at < window_end,
        )
        .group_by(models.EdgeDeviceEventInbox.store_id, models.EdgeDeviceEventInbox.event_type)
    ).all()
    totals: dict[int, int] = {}
    for store_id, event_type, count in rows:
        _write_aggregate(
            db, store_id=store_id, granularity=granularity, window_start=window_start,
            dimension=event_type, count=int(count), updated_at=updated_at,
        )
        totals[store_id] = totals.get(store_id, 0) + int(count)
    for store_id, count in totals.items():
        _write_aggregate(
            db, store_id=store_id, granularity=granularity, window_start=window_start,
            dimension="ALL", count=count, updated_at=updated_at,
        )
    return len(rows)


def aggregate_cycle(session_factory=SessionLocal, *, now: datetime | None = None,
                    max_windows_per_granularity: int = 96) -> dict[str, int]:
    """Process a bounded batch for each granularity; checkpoint and aggregates commit together."""
    if max_windows_per_granularity < 1 or max_windows_per_granularity > 1000:
        raise ValueError("max_windows_per_granularity must be between 1 and 1000")
    current = (now or utc_now()).astimezone(timezone.utc)
    retention_cutoff = current - timedelta(days=90)
    result: dict[str, int] = {}
    with session_factory() as db:
        try:
            for granularity, interval in INTERVALS.items():
                job_name = f"edge-observability-{granularity}-v1"
                checkpoint_table = models.EdgeObservabilityCheckpoint.__table__
                insert = _dialect_insert(db, checkpoint_table).values(
                    job_name=job_name, last_completed_window=None, updated_at=current
                ).on_conflict_do_nothing(index_elements=["job_name"])
                db.execute(insert)
                checkpoint = (
                    db.query(models.EdgeObservabilityCheckpoint)
                    .filter_by(job_name=job_name).with_for_update().one()
                )
                completed_boundary = floor_window(current, interval)
                if checkpoint.last_completed_window is None:
                    cursor = floor_window(retention_cutoff, interval) - interval
                else:
                    cursor = _database_utc(checkpoint.last_completed_window) - interval * OVERLAP_WINDOWS[granularity]
                processed = 0
                while cursor + interval <= completed_boundary and processed < max_windows_per_granularity:
                    _aggregate_window(db, granularity, cursor, cursor + interval, current)
                    checkpoint.last_completed_window = cursor
                    checkpoint.updated_at = current
                    cursor += interval
                    processed += 1
                result[granularity] = processed
            db.commit()
        except Exception:
            db.rollback()
            raise
    return result


def _delete_batch(db, model, timestamp_column, cutoff: datetime, batch_size: int) -> int:
    ids = select(model.id).where(timestamp_column < cutoff).order_by(timestamp_column, model.id).limit(batch_size)
    result = db.execute(delete(model).where(model.id.in_(ids)))
    return int(result.rowcount or 0)


def purge_expired(session_factory=SessionLocal, *, now: datetime | None = None,
                  retention_days: int = 90, batch_size: int = 500) -> dict[str, int]:
    """Delete bounded batches from observability tables only."""
    if not 1 <= retention_days <= 3650 or not 1 <= batch_size <= 5000:
        raise ValueError("invalid observability retention settings")
    cutoff = (now or utc_now()).astimezone(timezone.utc) - timedelta(days=retention_days)
    deleted = {"aggregates": 0, "supervisor_events": 0}
    with session_factory() as db:
        try:
            deleted["aggregates"] = _delete_batch(
                db, models.EdgeObservabilityAggregate,
                models.EdgeObservabilityAggregate.window_start, cutoff, batch_size,
            )
            deleted["supervisor_events"] = _delete_batch(
                db, models.EdgeSupervisorEvent, models.EdgeSupervisorEvent.occurred_at, cutoff, batch_size,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
    return deleted


def run_once() -> dict[str, object]:
    aggregated = aggregate_cycle()
    retention = purge_expired(
        retention_days=int(os.getenv("EDGE_OBSERVABILITY_RETENTION_DAYS", "90")),
        batch_size=int(os.getenv("EDGE_OBSERVABILITY_RETENTION_BATCH_SIZE", "500")),
    )
    return {"aggregated_windows": aggregated, "purged": retention}


def healthcheck(path: Path | None = None, *, now: float | None = None, max_age: int = 180) -> bool:
    target = path or Path(os.getenv("EDGE_OBSERVABILITY_HEARTBEAT_PATH", "/tmp/edge-observability-heartbeat.json"))
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        age = (time.time() if now is None else now) - float(payload["heartbeat_at"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False
    return 0 <= age <= max_age


def _write_health_heartbeat() -> None:
    target = Path(os.getenv("EDGE_OBSERVABILITY_HEARTBEAT_PATH", "/tmp/edge-observability-heartbeat.json"))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"pid": os.getpid(), "heartbeat_at": time.time()}), encoding="utf-8")
    os.replace(temporary, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent Edge observability aggregator and retention worker")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args(argv)
    if args.healthcheck:
        return 0 if healthcheck(max_age=int(os.getenv("EDGE_OBSERVABILITY_HEALTH_MAX_AGE", "180"))) else 1
    interval = float(os.getenv("EDGE_OBSERVABILITY_POLL_SECONDS", "60"))
    batch = int(os.getenv("EDGE_OBSERVABILITY_MAX_WINDOWS_PER_CYCLE", "96"))
    if not 5 <= interval <= 3600 or not 1 <= batch <= 1000:
        raise SystemExit("invalid Edge observability worker configuration")
    stop = threading.Event()

    def shutdown(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    logger.info("Edge observability worker started")
    while not stop.is_set():
        try:
            result = aggregate_cycle(max_windows_per_granularity=batch)
            retention = purge_expired(
                retention_days=int(os.getenv("EDGE_OBSERVABILITY_RETENTION_DAYS", "90")),
                batch_size=int(os.getenv("EDGE_OBSERVABILITY_RETENTION_BATCH_SIZE", "500")),
            )
            _write_health_heartbeat()
            logger.info("Edge observability cycle completed: windows=%s retention=%s", result, retention)
        except Exception as exc:
            # This process is deliberately independent; errors never reach business workers.
            logger.error("Edge observability cycle failed: error_type=%s", type(exc).__name__)
        stop.wait(interval)
    logger.info("Edge observability worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
