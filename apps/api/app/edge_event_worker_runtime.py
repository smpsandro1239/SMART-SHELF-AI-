"""Supervised polling process for the durable Edge event inbox.

TASK_ACKNOWLEDGED remains fail-closed: this runtime deliberately does not
inject BUILTIN_TRANSACTIONAL_HANDLERS. Domain handlers must be explicitly
provided by a separately reviewed deployment configuration.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import signal
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from app.database import SessionLocal
from app.edge_event_worker import process_one_edge_event

logger = logging.getLogger("smart_shelf.edge_event_worker")


def run_worker(
    *,
    worker_id: str,
    poll_interval: float,
    lease_seconds: int,
    stop_event: threading.Event,
    process_event: Callable[..., bool] = process_one_edge_event,
    once: bool = False,
) -> int:
    """Poll until shutdown; finish an in-flight event before stopping."""
    if not 0.5 <= poll_interval <= 300:
        raise ValueError("poll_interval must be between 0.5 and 300 seconds")
    if not 5 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds must be between 5 and 3600")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", worker_id or ""):
        raise ValueError("worker_id must be 1-160 safe ASCII characters")

    logger.info("Edge event worker started: worker_id=%s", worker_id)
    while not stop_event.is_set():
        try:
            processed = process_event(
                SessionLocal,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
        except Exception as exc:
            # Do not log exception text: provider/database errors may contain
            # connection details. The next poll retries after a bounded wait.
            logger.error(
                "Edge event polling failed; recovering: error_type=%s",
                type(exc).__name__,
            )
            if once:
                return 1
            stop_event.wait(poll_interval)
            continue

        if once:
            return 0
        if not processed:
            stop_event.wait(poll_interval)

    logger.info("Edge event worker stopped: worker_id=%s", worker_id)
    return 0


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
        )
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        signal.signal(signal.SIGINT, previous_sigint)


if __name__ == "__main__":
    raise SystemExit(main())
