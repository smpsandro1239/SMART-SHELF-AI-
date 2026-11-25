"""Run the durable Edge event worker as a standalone process.

Execute from apps/api after applying Alembic migrations through 0073 and
configuring the production database URL. Unsupported event types are
intentionally dead-lettered until their domain handlers are implemented.
"""
from __future__ import annotations

import argparse
import logging
import re
import signal
import socket
import threading
import time

from app.database import SessionLocal
from app.edge_event_worker import process_one_edge_event


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Smart Shelf Edge event worker.")
    parser.add_argument("--worker-id", default=None, help="Stable worker identifier (default: host and PID).")
    parser.add_argument("--lease-seconds", type=int, default=60)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--max-events", type=int, default=0, help="Stop after N claimed events; 0 runs indefinitely.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 5 <= args.lease_seconds <= 3600:
        build_parser().error("--lease-seconds must be between 5 and 3600")
    if not 0.1 <= args.poll_interval <= 60:
        build_parser().error("--poll-interval must be between 0.1 and 60 seconds")
    if args.max_events < 0:
        build_parser().error("--max-events cannot be negative")

    generated_id = f"edge-{socket.gethostname()}-{__import__('os').getpid()}"
    worker_id = args.worker_id or generated_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", worker_id):
        build_parser().error("--worker-id must contain 1-160 safe ASCII characters")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger("smart_shelf.edge_worker.runner")
    shutdown = threading.Event()

    def request_shutdown(signum, _frame):
        logger.info("Shutdown requested (signal=%s); finishing current event.", signum)
        shutdown.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    processed = 0
    logger.info("Starting Edge event worker id=%s lease_seconds=%s", worker_id, args.lease_seconds)
    while not shutdown.is_set():
        try:
            claimed = process_one_edge_event(
                SessionLocal,
                worker_id=worker_id,
                lease_seconds=args.lease_seconds,
            )
            if claimed:
                processed += 1
                if args.max_events and processed >= args.max_events:
                    break
            else:
                shutdown.wait(args.poll_interval)
        except Exception:
            logger.exception("Edge worker iteration failed; retrying after poll interval.")
            shutdown.wait(args.poll_interval)

    logger.info("Edge event worker stopped; claimed_events=%s", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
