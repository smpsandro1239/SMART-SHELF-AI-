"""Non-blocking, best-effort persistence for allowlisted supervisor events."""
from __future__ import annotations
import logging
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable
from app.database import SessionLocal
from app.models import EdgeSupervisorEvent
logger = logging.getLogger("smart_shelf.edge_supervisor_events")
EVENT_TYPES = {"STARTED", "RESTARTING", "FAILED", "STOPPED", "CHILD_EXITED", "HEARTBEAT_STALE"}
REASON_CODES = {"CHILD_CONFIGURATION_ERROR", "CHILD_EXITED", "CHILD_HEARTBEAT_STALE", "CHILD_HEARTBEAT_MISSING", "SPAWN_FAILED", "SHUTDOWN_REQUESTED", "UNKNOWN"}
class AsyncSupervisorEventWriter:
    """Bounded queue + daemon DB writer. emit() never waits for database I/O."""
    def __init__(self, session_factory: Callable = SessionLocal, *, max_queue_size: int = 256):
        if max_queue_size < 1: raise ValueError("max_queue_size must be positive")
        self._session_factory = session_factory
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._closing = threading.Event()
        self._thread: threading.Thread | None = None
    def start(self) -> None:
        if self._thread is not None: return
        self._thread = threading.Thread(target=self._run, name="edge-supervisor-event-writer", daemon=True)
        self._thread.start()
    def emit(self, *, event_type: str, supervisor_instance_id: str, worker_id: str | None, reason_code: str | None = None, restart_count: int = 0, exit_code: int | None = None) -> bool:
        if event_type not in EVENT_TYPES or (reason_code is not None and reason_code not in REASON_CODES):
            logger.warning("Rejected non-allowlisted supervisor event")
            return False
        if not isinstance(restart_count, int) or restart_count < 0: return False
        payload = {"event_key": uuid.uuid4().hex + uuid.uuid4().hex, "supervisor_instance_id": str(supervisor_instance_id)[:120], "event_type": event_type, "worker_id": str(worker_id)[:160] if worker_id is not None else None, "reason_code": reason_code, "restart_count": restart_count, "exit_code": exit_code if isinstance(exit_code, int) else None, "occurred_at": datetime.now(timezone.utc)}
        try:
            self._queue.put_nowait(payload)
            return True
        except queue.Full:
            logger.warning("Supervisor event queue full; dropping observability event")
            return False
    def _run(self) -> None:
        while not self._closing.is_set() or not self._queue.empty():
            try: payload = self._queue.get(timeout=0.1)
            except queue.Empty: continue
            try:
                with self._session_factory() as db:
                    db.add(EdgeSupervisorEvent(**payload))
                    db.commit()
            except Exception as exc:
                logger.warning("Supervisor event persistence failed: error_type=%s", type(exc).__name__)
                try: db.rollback()
                except Exception: pass
            finally:
                self._queue.task_done()
    def close(self, *, timeout: float = 2.0) -> None:
        self._closing.set()
        if self._thread is not None: self._thread.join(timeout=max(0.0, timeout))
