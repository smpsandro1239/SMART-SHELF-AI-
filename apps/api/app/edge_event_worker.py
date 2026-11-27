"""Operational Edge event worker with lease heartbeats and explicit handler routing.

Only DEVICE_HEARTBEAT is currently a safe built-in no-op: its telemetry is
persisted transactionally during ingestion. Other event types are sent to the
dead-letter queue until their domain handlers and durable side effects exist.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.edge_event_processing import (
    EdgeEventProcessingError,
    claim_next_edge_event,
    complete_edge_event,
    complete_edge_event_transactionally,
    fail_edge_event,
    renew_edge_event_lease,
)

logger = logging.getLogger("smart_shelf.edge_worker")


class EdgeEventHandlerError(RuntimeError):
    """A handler failure with an explicit retry policy."""

    def __init__(self, code: str, *, retryable: bool = True):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


EdgeEventHandler = Callable[[dict[str, Any]], None]
TransactionalEdgeEventHandler = Callable[[Session, dict[str, Any]], None]

# Imported after EdgeEventHandlerError is defined: the service uses that error type.
from app.edge_task_acknowledgement_service import apply_edge_task_acknowledgement


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
) -> bool:
    """Claim and process at most one event; return False when the queue is idle."""
    with session_factory() as db:
        claim = claim_next_edge_event(
            db, worker_id=worker_id, lease_seconds=lease_seconds
        )
    if claim is None:
        return False

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
            except Exception:
                lease_lost.set()
                logger.exception(
                    "Edge event lease renewal failed; abandoning local result: inbox_id=%s",
                    claim["inbox_id"],
                )
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

    if transactional_handler is not None:
        # Stop renewals before acquiring the processing row lock. The fenced
        # handler and PROCESSED transition then share one database transaction.
        stop_and_join_heartbeat()
        if lease_lost.is_set():
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
                    fail_edge_event(
                        db, processing_id=claim["processing_id"], worker_id=worker_id,
                        fencing_token=claim["fencing_token"], error_code=exc.code,
                        retryable=exc.retryable,
                    )
                except EdgeEventProcessingError:
                    logger.warning("Transactional Edge handler lost its lease: inbox_id=%s", claim["inbox_id"])
        except Exception:
            with session_factory() as db:
                try:
                    fail_edge_event(
                        db, processing_id=claim["processing_id"], worker_id=worker_id,
                        fencing_token=claim["fencing_token"], error_code="WORKER_ERROR",
                        retryable=True,
                    )
                except EdgeEventProcessingError:
                    logger.warning("Transactional Edge handler failed after lease loss: inbox_id=%s", claim["inbox_id"])
            logger.exception("Transactional Edge event handler failed: inbox_id=%s", claim["inbox_id"])
        else:
            logger.info(
                "Edge event processed transactionally: type=%s inbox_id=%s attempt=%s",
                claim["event_type"], claim["inbox_id"], claim["attempt_count"],
            )
        return True

    try:
        handler(claim)
    except EdgeEventHandlerError as exc:
        stop_and_join_heartbeat()
        if lease_lost.is_set():
            return True
        with session_factory() as db:
            fail_edge_event(
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
        return True
    except Exception:
        stop_and_join_heartbeat()
        if lease_lost.is_set():
            return True
        with session_factory() as db:
            fail_edge_event(
                db,
                processing_id=claim["processing_id"],
                worker_id=worker_id,
                fencing_token=claim["fencing_token"],
                error_code="WORKER_ERROR",
                retryable=True,
            )
        logger.exception("Edge event handler failed: inbox_id=%s", claim["inbox_id"])
        return True
    else:
        stop_and_join_heartbeat()
        if lease_lost.is_set():
            # A worker whose lease could not be renewed must never acknowledge
            # side effects; a replacement worker will recover the expired lease.
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
        return True
