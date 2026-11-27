"""Operational Edge event worker with lease heartbeats and explicit handler routing.

Only DEVICE_HEARTBEAT is currently a safe built-in no-op: its telemetry is
persisted transactionally during ingestion. Other event types are sent to the
dead-letter queue until their domain handlers and durable side effects exist.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import socket
import threading
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.database import SessionLocal

from app.edge_event_errors import EdgeEventHandlerError
from app.edge_task_acknowledgement_service import apply_edge_task_acknowledgement
from app.edge_event_processing import (
    EdgeEventProcessingError,
    claim_next_edge_event,
    complete_edge_event,
    complete_edge_event_transactionally,
    fail_edge_event,
    renew_edge_event_lease,
)

logger = logging.getLogger("smart_shelf.edge_worker")


EdgeEventHandler = Callable[[dict[str, Any]], None]
TransactionalEdgeEventHandler = Callable[[Session, dict[str, Any]], None]


def _heartbeat_event_handler(event: dict[str, Any]) -> None:
    """No-op by design: heartbeat telemetry is committed at ingestion time."""
    if event.get("event_type") != "DEVICE_HEARTBEAT":
        raise EdgeEventHandlerError("INVALID_HANDLER_ROUTING", retryable=False)


BUILTIN_HANDLERS: dict[str, EdgeEventHandler] = {
    "DEVICE_HEARTBEAT": _heartbeat_event_handler,
}


BUILTIN_TRANSACTIONAL_HANDLERS: dict[str, TransactionalEdgeEventHandler] = {
    # Persist the device declaration and mark its inbox processing row PROCESSED
    # in the same fenced SQL transaction. COMPLETED remains review-only.
    "TASK_ACKNOWLEDGED": apply_edge_task_acknowledgement,
}


def process_one_edge_event(
    session_factory: sessionmaker,
    *,
    worker_id: str,
    lease_seconds: int = 60,
    handlers: dict[str, EdgeEventHandler] | None = None,
    transactional_handlers: dict[str, TransactionalEdgeEventHandler] | None = None,
    outcome_observer: Callable[[str, str | None], None] | None = None,
    lease_observer: Callable[[bool], None] | None = None,
) -> bool:
    """Claim and process at most one event; return False when the queue is idle."""
    with session_factory() as db:
        claim = claim_next_edge_event(
            db, worker_id=worker_id, lease_seconds=lease_seconds
        )
    if claim is None:
        return False

    event_started_at = time.monotonic()

    def log_outcome(
        outcome: str,
        *,
        error_code: str | None = None,
        error_type: str | None = None,
        level: int = logging.INFO,
    ) -> None:
        logger.log(
            level,
            "edge_event_outcome outcome=%s event_type=%s event_id=%s inbox_id=%s "
            "processing_id=%s store_id=%s device_id=%s worker_id=%s attempt=%s "
            "duration_ms=%s error_code=%s error_type=%s",
            outcome,
            claim["event_type"],
            claim["event_id"],
            claim["inbox_id"],
            claim["processing_id"],
            claim["store_id"],
            claim["device_id"],
            worker_id,
            claim["attempt_count"],
            round((time.monotonic() - event_started_at) * 1000),
            error_code,
            error_type,
        )
        if outcome_observer is not None:
            try:
                outcome_observer(outcome, error_code)
            except Exception as observer_error:
                logger.error(
                    "Edge metrics outcome observer failed: error_type=%s",
                    type(observer_error).__name__,
                )

    log_outcome("ACK_CLAIMED" if claim["event_type"] == "TASK_ACKNOWLEDGED" else "CLAIMED")

    routes = BUILTIN_HANDLERS if handlers is None else handlers
    handler = routes.get(claim["event_type"])
    # Keep domain handlers opt-in: TASK_ACKNOWLEDGED is not enabled by the
    # production worker until the complete CI validation is accepted.
    transactional_routes = transactional_handlers or {}
    transactional_handler = transactional_routes.get(claim["event_type"])
    if handler is None and transactional_handler is None:
        with session_factory() as db:
            state = fail_edge_event(
                db,
                processing_id=claim["processing_id"],
                worker_id=worker_id,
                fencing_token=claim["fencing_token"],
                error_code="HANDLER_NOT_IMPLEMENTED",
                retryable=False,
            )
        logger.error(
            "Edge event moved to %s: type=%s inbox_id=%s",
            state, claim["event_type"], claim["inbox_id"],
        )
        log_outcome(state, error_code="HANDLER_NOT_IMPLEMENTED", level=logging.ERROR)
        return True

    stop_heartbeat = threading.Event()
    lease_lost = threading.Event()
    heartbeat_interval = max(1.0, lease_seconds / 3.0)

    def renew_until_stopped() -> None:
        while not stop_heartbeat.wait(heartbeat_interval):
            try:
                with session_factory() as heartbeat_db:
                    renew_edge_event_lease(
                        heartbeat_db,
                        processing_id=claim["processing_id"],
                        worker_id=worker_id,
                        fencing_token=claim["fencing_token"],
                        lease_seconds=lease_seconds,
                    )
                if lease_observer is not None:
                    try:
                        lease_observer(True)
                    except Exception as observer_error:
                        logger.error(
                            "Edge metrics lease observer failed: error_type=%s",
                            type(observer_error).__name__,
                        )
            except Exception as exc:
                if lease_observer is not None:
                    try:
                        lease_observer(False)
                    except Exception as observer_error:
                        logger.error(
                            "Edge metrics lease observer failed: error_type=%s",
                            type(observer_error).__name__,
                        )
                lease_lost.set()
                # Database/driver exception text can contain connection details.
                # Keep diagnostics useful without logging provider-supplied text.
                logger.error(
                    "Edge event lease renewal failed; abandoning local result: "
                    "inbox_id=%s error_type=%s",
                    claim["inbox_id"], type(exc).__name__,
                )
                log_outcome("LEASE_LOST", error_type=type(exc).__name__, level=logging.ERROR)
                return

    heartbeat_thread = threading.Thread(
        target=renew_until_stopped,
        name=f"edge-lease-{claim['processing_id']}",
        daemon=True,
    )
    heartbeat_thread.start()

    def stop_and_join_heartbeat() -> None:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=heartbeat_interval + 1)
        if heartbeat_thread.is_alive():
            # A renewal may still be in flight. Do not race it with complete/fail;
            # leave the lease for normal expiry and fenced recovery by another worker.
            lease_lost.set()
            logger.error(
                "Edge event heartbeat did not stop promptly; abandoning local result: inbox_id=%s",
                claim["inbox_id"],
            )
            log_outcome("LEASE_LOST", error_code="HEARTBEAT_THREAD_STUCK", level=logging.ERROR)

    if transactional_handler is not None:
        # Stop renewals before acquiring the processing row lock. The fenced
        # handler and PROCESSED transition then share one database transaction.
        stop_and_join_heartbeat()
        if lease_lost.is_set():
            log_outcome("LEASE_LOST", level=logging.ERROR)
            return True
        try:
            with session_factory() as db:
                complete_edge_event_transactionally(
                    db,
                    processing_id=claim["processing_id"],
                    worker_id=worker_id,
                    fencing_token=claim["fencing_token"],
                    event=claim,
                    handler=transactional_handler,
                )
        except EdgeEventHandlerError as exc:
            with session_factory() as db:
                try:
                    state = fail_edge_event(
                        db, processing_id=claim["processing_id"], worker_id=worker_id,
                        fencing_token=claim["fencing_token"], error_code=exc.code,
                        retryable=exc.retryable,
                    )
                    log_outcome(
                        "ACK_REJECTED" if claim["event_type"] == "TASK_ACKNOWLEDGED" else state,
                        error_code=exc.code,
                        level=logging.WARNING,
                    )
                except EdgeEventProcessingError:
                    logger.warning("Transactional Edge handler lost its lease: inbox_id=%s", claim["inbox_id"])
                    log_outcome("LEASE_LOST", error_code=exc.code, level=logging.ERROR)
        except Exception as exc:
            with session_factory() as db:
                try:
                    state = fail_edge_event(
                        db, processing_id=claim["processing_id"], worker_id=worker_id,
                        fencing_token=claim["fencing_token"], error_code="WORKER_ERROR",
                        retryable=True,
                    )
                    log_outcome(
                        "ACK_REJECTED" if claim["event_type"] == "TASK_ACKNOWLEDGED" else state,
                        error_code="WORKER_ERROR",
                        error_type=type(exc).__name__,
                        level=logging.ERROR,
                    )
                except EdgeEventProcessingError:
                    logger.warning("Transactional Edge handler failed after lease loss: inbox_id=%s", claim["inbox_id"])
                    log_outcome("LEASE_LOST", error_type=type(exc).__name__, level=logging.ERROR)
            logger.error(
                "Transactional Edge event handler failed: inbox_id=%s error_type=%s",
                claim["inbox_id"], type(exc).__name__,
            )
        else:
            logger.info(
                "Edge event processed transactionally: type=%s inbox_id=%s attempt=%s",
                claim["event_type"], claim["inbox_id"], claim["attempt_count"],
            )
            log_outcome("ACK_RECORDED" if claim["event_type"] == "TASK_ACKNOWLEDGED" else "PROCESSED")
        return True

    try:
        handler(claim)
    except EdgeEventHandlerError as exc:
        stop_and_join_heartbeat()
        if lease_lost.is_set():
            log_outcome("LEASE_LOST", error_code=exc.code, level=logging.ERROR)
            return True
        with session_factory() as db:
            state = fail_edge_event(
                db,
                processing_id=claim["processing_id"],
                worker_id=worker_id,
                fencing_token=claim["fencing_token"],
                error_code=exc.code,
                retryable=exc.retryable,
            )
        logger.warning(
            "Edge event handler rejected event: code=%s inbox_id=%s",
            exc.code, claim["inbox_id"],
        )
        log_outcome(state, error_code=exc.code, level=logging.WARNING)
        return True
    except Exception as exc:
        stop_and_join_heartbeat()
        if lease_lost.is_set():
            log_outcome("LEASE_LOST", error_type=type(exc).__name__, level=logging.ERROR)
            return True
        with session_factory() as db:
            state = fail_edge_event(
                db,
                processing_id=claim["processing_id"],
                worker_id=worker_id,
                fencing_token=claim["fencing_token"],
                error_code="WORKER_ERROR",
                retryable=True,
            )
        logger.error(
            "Edge event handler failed: inbox_id=%s error_type=%s",
            claim["inbox_id"], type(exc).__name__,
        )
        log_outcome(state, error_code="WORKER_ERROR", error_type=type(exc).__name__, level=logging.ERROR)
        return True
    else:
        stop_and_join_heartbeat()
        if lease_lost.is_set():
            # A worker whose lease could not be renewed must never acknowledge
            # side effects; a replacement worker will recover the expired lease.
            log_outcome("LEASE_LOST", level=logging.ERROR)
            return True
        with session_factory() as db:
            complete_edge_event(
                db,
                processing_id=claim["processing_id"],
                worker_id=worker_id,
                fencing_token=claim["fencing_token"],
            )
        logger.info(
            "Edge event processed: type=%s inbox_id=%s attempt=%s",
            claim["event_type"], claim["inbox_id"], claim["attempt_count"],
        )
        log_outcome("PROCESSED")
        return True


def run_worker(
    *,
    worker_id: str,
    poll_interval: float,
    lease_seconds: int,
    stop_event: threading.Event,
    process_event: Callable[..., bool] = process_one_edge_event,
    once: bool = False,
    enable_transactional_ack: bool = False,
    transactional_handlers: dict[str, Callable[..., Any]] | None = None,
) -> int:
    """Poll until shutdown; finish an in-flight event before stopping."""
    if enable_transactional_ack and not transactional_handlers:
        raise ValueError("transactional ACK requires an explicitly injected non-empty handler registry")
    if not enable_transactional_ack and transactional_handlers is not None:
        raise ValueError("transactional handlers cannot be injected while ACK is disabled")
    if not 0.5 <= poll_interval <= 300:
        raise ValueError("poll_interval must be between 0.5 and 300 seconds")
    if not 5 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be between 5 and 3600")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", worker_id or ""):
        raise ValueError("worker_id must be 1-160 safe ASCII characters")

    logger.info("Edge event worker started: worker_id=%s", worker_id)
    heartbeat_path = os.getenv("EDGE_EVENT_CHILD_HEARTBEAT_PATH")
    metrics: dict[str, Any] = {
        "poll_attempts": 0,
        "claimed_events": 0,
        "idle_polls": 0,
        "poll_failures": 0,
        "events_processed": 0,
        "events_retried": 0,
        "events_dead_lettered": 0,
        "handler_failures": 0,
        "duplicate_events": 0,
        "lease_renewals": 0,
        "lease_renewal_failures": 0,
        "lease_losses": 0,
        "ack_claimed": 0,
        "ack_recorded": 0,
        "ack_rejected": 0,
        "last_outcome": None,
        "last_outcome_at": None,
        "last_poll_duration_ms": 0,
        "last_event_at": None,
        "last_error_type": None,
    }
    metrics_lock = threading.Lock()

    def increment_metric(name: str, amount: int = 1) -> None:
        with metrics_lock:
            metrics[name] += amount

    def observe_outcome(outcome: str, error_code: str | None) -> None:
        with metrics_lock:
            metrics["last_outcome"] = outcome
            metrics["last_outcome_at"] = time.time()
            outcome_counters = {
                "PROCESSED": "events_processed",
                "RETRY": "events_retried",
                "DEAD_LETTER": "events_dead_lettered",
                "LEASE_LOST": "lease_losses",
                "ACK_CLAIMED": "ack_claimed",
                "ACK_RECORDED": "ack_recorded",
                "ACK_REJECTED": "ack_rejected",
            }
            counter = outcome_counters.get(outcome)
            if counter is not None:
                metrics[counter] += 1
            if outcome in {"RETRY", "DEAD_LETTER", "ACK_REJECTED"}:
                metrics["handler_failures"] += 1
            if error_code in {"DUPLICATE_ACK_EVENT", "DUPLICATE_EVENT"}:
                metrics["duplicate_events"] += 1

    def observe_lease_renewal(succeeded: bool) -> None:
        increment_metric("lease_renewals" if succeeded else "lease_renewal_failures")

    def write_heartbeat() -> None:
        if not heartbeat_path:
            return
        target = Path(heartbeat_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        with metrics_lock:
            snapshot = metrics.copy()
        payload = {
            "schema_version": 2,
            "pid": os.getpid(),
            "heartbeat_at": time.time(),
            "metrics": snapshot,
        }
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, target)

    while not stop_event.is_set():
        try:
            write_heartbeat()
        except OSError as exc:
            logger.error("Edge worker heartbeat write failed: error_type=%s", type(exc).__name__)
            return 1

        increment_metric("poll_attempts")
        poll_started = time.monotonic()
        try:
            process_kwargs: dict[str, Any] = {
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
            }
            if process_event is process_one_edge_event:
                process_kwargs["outcome_observer"] = observe_outcome
                process_kwargs["lease_observer"] = observe_lease_renewal
            if enable_transactional_ack:
                process_kwargs["transactional_handlers"] = transactional_handlers
            processed = process_event(SessionLocal, **process_kwargs)
        except Exception as exc:
            with metrics_lock:
                metrics["poll_failures"] += 1
                metrics["last_error_type"] = type(exc).__name__
                metrics["last_poll_duration_ms"] = round((time.monotonic() - poll_started) * 1000)
            logger.error(
                "Edge event polling failed; recovering: error_type=%s",
                type(exc).__name__,
            )
            try:
                write_heartbeat()
            except OSError as heartbeat_exc:
                logger.error("Edge worker heartbeat write failed: error_type=%s", type(heartbeat_exc).__name__)
                return 1
            if once:
                return 1
            stop_event.wait(poll_interval)
            continue

        with metrics_lock:
            metrics["last_poll_duration_ms"] = round((time.monotonic() - poll_started) * 1000)
            metrics["last_error_type"] = None
            if processed:
                metrics["claimed_events"] += 1
                metrics["last_event_at"] = time.time()
            else:
                metrics["idle_polls"] += 1

        try:
            write_heartbeat()
        except OSError as exc:
            logger.error("Edge worker heartbeat write failed: error_type=%s", type(exc).__name__)
            return 1

        if once:
            return 0
        if not processed:
            stop_event.wait(poll_interval)

    logger.info("Edge event worker stopped: worker_id=%s", worker_id)
    return 0


def resolve_transactional_ack_configuration(
    enabled_value: str | None = None,
    registry_value: str | None = None,
) -> tuple[bool, dict[str, Callable[..., Any]] | None]:
    """Resolve the dedicated feature flag and explicit handler registry selector.

    A true flag alone never activates handlers. The operator must also select
    the exact supported registry; the resulting mapping is then injected into
    run_worker and process_one_edge_event explicitly.
    """
    raw_enabled = (enabled_value if enabled_value is not None else os.getenv(
        "EDGE_TASK_ACKNOWLEDGEMENT_ENABLED", "false"
    )).strip().lower()
    registry = (registry_value if registry_value is not None else os.getenv(
        "EDGE_TASK_ACKNOWLEDGEMENT_HANDLER_REGISTRY", ""
    )).strip()

    if raw_enabled not in {"true", "false"}:
        raise ValueError("EDGE_TASK_ACKNOWLEDGEMENT_ENABLED must be true or false")
    if raw_enabled == "false":
        if registry:
            raise ValueError("handler registry cannot be selected while TASK_ACKNOWLEDGED is disabled")
        return False, None
    if registry != "builtin-v1":
        raise ValueError("enabled TASK_ACKNOWLEDGED requires explicit EDGE_TASK_ACKNOWLEDGEMENT_HANDLER_REGISTRY=builtin-v1")
    return True, BUILTIN_TRANSACTIONAL_HANDLERS


def _default_worker_id() -> str:
    configured = os.getenv("EDGE_EVENT_WORKER_ID", "").strip()
    return configured or f"{socket.gethostname()}-{os.getpid()}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Supervised SMART SHELF AI Edge event inbox worker"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.getenv("EDGE_EVENT_POLL_INTERVAL", "5")),
        help="Seconds between idle queue checks (0.5-300)",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=int(os.getenv("EDGE_EVENT_LEASE_SECONDS", "60")),
        help="Processing lease duration (5-3600)",
    )
    parser.add_argument("--worker-id", default=_default_worker_id())
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one event and exit (diagnostics only)",
    )
    args = parser.parse_args(argv)

    if not 0.5 <= args.poll_interval <= 300:
        parser.error("--poll-interval must be between 0.5 and 300 seconds")
    if not 5 <= args.lease_seconds <= 3600:
        parser.error("--lease-seconds must be between 5 and 3600 seconds")

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        enable_transactional_ack, transactional_handlers = resolve_transactional_ack_configuration()
    except ValueError as exc:
        logger.error("Edge transactional ACK configuration rejected: error_type=%s", type(exc).__name__)
        return 2

    stop_event = threading.Event()

    def request_shutdown(signum: int, _frame: Any) -> None:
        logger.info("Shutdown signal received: signal=%s", signum)
        stop_event.set()

    previous_sigterm = signal.signal(signal.SIGTERM, request_shutdown)
    previous_sigint = signal.signal(signal.SIGINT, request_shutdown)
    try:
        return run_worker(
            worker_id=args.worker_id,
            poll_interval=args.poll_interval,
            lease_seconds=args.lease_seconds,
            stop_event=stop_event,
            once=args.once,
            enable_transactional_ack=enable_transactional_ack,
            transactional_handlers=transactional_handlers,
        )
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)


if __name__ == "__main__":
    raise SystemExit(main())
