"""Independent process supervisor for the Edge event worker.

The supervisor owns child lifecycle, restart backoff and operational heartbeat.
The child heartbeat is emitted by the worker's polling loop; a stale heartbeat
causes the child to be terminated and replaced. No domain handler is enabled here.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("smart_shelf.edge_supervisor")


@dataclass(frozen=True)
class SupervisorConfig:
    worker_id: str
    poll_interval: float
    lease_seconds: int
    heartbeat_interval: float
    heartbeat_timeout: float
    restart_base_seconds: float
    restart_max_seconds: float
    shutdown_timeout: float
    state_path: Path
    child_heartbeat_path: Path


def calculate_backoff(consecutive_failures: int, base: float, maximum: float) -> float:
    if consecutive_failures < 1:
        return 0.0
    return min(maximum, base * (2 ** min(consecutive_failures - 1, 30)))


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def child_heartbeat(path: Path | None = None) -> None:
    target = path or Path(os.getenv("EDGE_EVENT_CHILD_HEARTBEAT_PATH", "/tmp/edge-worker-child.json"))
    _write_json_atomic(target, {"pid": os.getpid(), "heartbeat_at": time.time()})


def healthcheck(
    state_path: Path,
    child_heartbeat_path: Path,
    *,
    now: float | None = None,
    heartbeat_timeout: float = 120.0,
    supervisor_timeout: float = 30.0,
) -> bool:
    current = time.time() if now is None else now
    state = _read_json(state_path)
    child = _read_json(child_heartbeat_path)
    if state is None or child is None or state.get("status") != "RUNNING":
        return False
    try:
        supervisor_age = current - float(state["heartbeat_at"])
        child_age = current - float(child["heartbeat_at"])
        supervisor_pid = int(state["supervisor_pid"])
        child_pid = int(state["child_pid"])
        recorded_child_pid = int(child["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    if supervisor_age < 0 or child_age < 0:
        return False
    if supervisor_age > supervisor_timeout or child_age > heartbeat_timeout:
        return False
    if child_pid != recorded_child_pid:
        return False
    try:
        os.kill(supervisor_pid, 0)
        os.kill(child_pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _terminate_child(process: subprocess.Popen[Any], timeout: float) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            return
        process.wait(timeout=timeout)


def run_supervisor(
    config: SupervisorConfig,
    stop_event: threading.Event,
    *,
    popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    event_sink: Callable[..., None] | None = None,
) -> int:
    consecutive_failures = 0
    restart_count = 0
    last_restart_at: float | None = None
    last_exit_code: int | None = None
    supervisor_instance_id = uuid.uuid4().hex

    def emit(event_type: str, *, reason_code: str | None = None, exit_code: int | None = None) -> None:
        if event_sink is None:
            return
        try:
            event_sink(event_type=event_type, supervisor_instance_id=supervisor_instance_id,
                       worker_id=config.worker_id, reason_code=reason_code,
                       restart_count=restart_count, exit_code=exit_code)
        except Exception:
            logger.warning("Supervisor event enqueue failed")

    emit("STARTED")

    for path in (config.state_path, config.child_heartbeat_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    while not stop_event.is_set():
        try:
            config.child_heartbeat_path.unlink(missing_ok=True)
        except OSError:
            logger.error("Cannot clear stale child heartbeat before spawn")
            return 1

        environment = os.environ.copy()
        environment["EDGE_EVENT_CHILD_HEARTBEAT_PATH"] = str(config.child_heartbeat_path)
        command = [
            sys.executable, "-m", "app.edge_event_worker",
            "--worker-id", f"{config.worker_id}-child",
            "--poll-interval", str(config.poll_interval),
            "--lease-seconds", str(config.lease_seconds),
        ]
        try:
            child = popen_factory(command, env=environment, close_fds=True)
        except OSError as exc:
            last_exit_code = None
            consecutive_failures += 1
            restart_count += 1
            delay = calculate_backoff(consecutive_failures, config.restart_base_seconds, config.restart_max_seconds)
            emit("RESTARTING", reason_code="SPAWN_FAILED")
            _write_json_atomic(config.state_path, {
                "status": "RESTARTING", "supervisor_pid": os.getpid(),
                "heartbeat_at": wall_clock(), "child_pid": None,
                "restart_count": restart_count, "consecutive_failures": consecutive_failures,
                "last_restart_at": last_restart_at, "last_exit_code": last_exit_code,
                "error_type": type(exc).__name__,
            })
            stop_event.wait(delay)
            continue

        emit("STARTED")
        started_at = monotonic()
        last_heartbeat_at = wall_clock()
        child_seen = False
        failure_reason: str | None = None

        while not stop_event.is_set():
            now_mono = monotonic()
            child_status = _read_json(config.child_heartbeat_path)
            if child_status is not None:
                try:
                    child_seen = int(child_status["pid"]) == child.pid
                    child_heartbeat_at = float(child_status["heartbeat_at"])
                except (KeyError, TypeError, ValueError):
                    child_seen = False
                    child_heartbeat_at = 0.0
                if child_seen and wall_clock() - child_heartbeat_at > config.heartbeat_timeout:
                    failure_reason = "CHILD_HEARTBEAT_STALE"
                    emit("HEARTBEAT_STALE", reason_code="CHILD_HEARTBEAT_STALE")
                    break
            elif now_mono - started_at > config.heartbeat_timeout:
                failure_reason = "CHILD_HEARTBEAT_MISSING"
                emit("HEARTBEAT_STALE", reason_code="CHILD_HEARTBEAT_MISSING")
                break

            return_code = child.poll()
            if return_code is not None:
                last_exit_code = return_code
                failure_reason = "CHILD_CONFIGURATION_ERROR" if return_code == 2 else "CHILD_EXITED"
                emit("CHILD_EXITED", reason_code=failure_reason, exit_code=return_code)
                break

            last_heartbeat_at = wall_clock()
            _write_json_atomic(config.state_path, {
                "status": "RUNNING", "supervisor_pid": os.getpid(),
                "heartbeat_at": last_heartbeat_at, "child_pid": child.pid,
                "child_heartbeat_at": child_heartbeat_at if child_seen else None,
                "worker_metrics": child_status.get("metrics") if child_seen and child_status is not None else None,
                "restart_count": restart_count, "consecutive_failures": consecutive_failures,
                "last_restart_at": last_restart_at, "last_exit_code": last_exit_code,
                "failure_reason": None,
            })
            stop_event.wait(config.heartbeat_interval)

        if not stop_event.is_set() and failure_reason == "CHILD_CONFIGURATION_ERROR":
            emit("FAILED", reason_code="CHILD_CONFIGURATION_ERROR", exit_code=last_exit_code)
            logger.error("Edge worker configuration is invalid; supervisor remains degraded until operator restart")
            while not stop_event.is_set():
                _write_json_atomic(config.state_path, {
                    "status": "FAILED", "supervisor_pid": os.getpid(),
                    "heartbeat_at": wall_clock(), "child_pid": None,
                    "restart_count": restart_count, "consecutive_failures": consecutive_failures,
                    "last_restart_at": last_restart_at, "last_exit_code": last_exit_code,
                    "failure_reason": failure_reason,
                })
                stop_event.wait(config.heartbeat_interval)
            _write_json_atomic(config.state_path, {
                "status": "STOPPED", "supervisor_pid": os.getpid(),
                "heartbeat_at": wall_clock(), "child_pid": None,
                "restart_count": restart_count, "consecutive_failures": consecutive_failures,
                "last_restart_at": last_restart_at, "last_exit_code": last_exit_code,
                "failure_reason": None,
            })
            return 0

        if stop_event.is_set():
            emit("STOPPED", reason_code="SHUTDOWN_REQUESTED", exit_code=child.poll())
            _terminate_child(child, config.shutdown_timeout)
            _write_json_atomic(config.state_path, {
                "status": "STOPPED", "supervisor_pid": os.getpid(),
                "heartbeat_at": wall_clock(), "child_pid": None,
                "restart_count": restart_count, "consecutive_failures": consecutive_failures,
                "last_restart_at": last_restart_at, "last_exit_code": child.poll(),
                "failure_reason": None,
            })
            return 0

        _terminate_child(child, config.shutdown_timeout)
        runtime = monotonic() - started_at
        if runtime >= max(config.heartbeat_timeout, config.lease_seconds * 2):
            consecutive_failures = 0
        consecutive_failures += 1
        restart_count += 1
        last_restart_at = wall_clock()
        delay = calculate_backoff(consecutive_failures, config.restart_base_seconds, config.restart_max_seconds)
        emit("RESTARTING", reason_code=failure_reason or "UNKNOWN", exit_code=last_exit_code)
        logger.warning(
            "Edge worker child will restart: reason=%s restart_count=%s backoff_seconds=%s",
            failure_reason or "UNKNOWN", restart_count, delay,
        )
        _write_json_atomic(config.state_path, {
            "status": "RESTARTING", "supervisor_pid": os.getpid(),
            "heartbeat_at": wall_clock(), "child_pid": None,
            "restart_count": restart_count, "consecutive_failures": consecutive_failures,
            "last_restart_at": last_restart_at, "last_exit_code": last_exit_code,
            "failure_reason": failure_reason,
        })
        stop_event.wait(delay)

    return 0


def _acquire_singleton_lock(path: Path) -> int | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    os.ftruncate(descriptor, 0)
    os.write(descriptor, str(os.getpid()).encode("ascii"))
    return descriptor


def _config_from_env() -> SupervisorConfig:
    lease = int(os.getenv("EDGE_EVENT_LEASE_SECONDS", "60"))
    poll = float(os.getenv("EDGE_EVENT_POLL_INTERVAL", "5"))
    heartbeat_interval = float(os.getenv("EDGE_SUPERVISOR_HEARTBEAT_INTERVAL", "2"))
    heartbeat_timeout = float(os.getenv("EDGE_SUPERVISOR_HEARTBEAT_TIMEOUT", str(max(lease * 2, 120))))
    return SupervisorConfig(
        worker_id=os.getenv("EDGE_EVENT_WORKER_ID", "edge-event-worker-1"),
        poll_interval=poll,
        lease_seconds=lease,
        heartbeat_interval=heartbeat_interval,
        heartbeat_timeout=heartbeat_timeout,
        restart_base_seconds=float(os.getenv("EDGE_SUPERVISOR_RESTART_BASE_SECONDS", "1")),
        restart_max_seconds=float(os.getenv("EDGE_SUPERVISOR_RESTART_MAX_SECONDS", "60")),
        shutdown_timeout=float(os.getenv("EDGE_SUPERVISOR_SHUTDOWN_TIMEOUT", "10")),
        state_path=Path(os.getenv("EDGE_SUPERVISOR_STATE_PATH", "/tmp/edge-supervisor-state.json")),
        child_heartbeat_path=Path(os.getenv("EDGE_EVENT_CHILD_HEARTBEAT_PATH", "/tmp/edge-worker-child.json")),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent Edge event worker supervisor")
    parser.add_argument("--healthcheck", action="store_true", help="Return non-zero unless supervisor and child heartbeats are healthy")
    args = parser.parse_args(argv)
    config = _config_from_env()
    if not 0.5 <= config.heartbeat_interval <= 30:
        parser.error("EDGE_SUPERVISOR_HEARTBEAT_INTERVAL must be between 0.5 and 30 seconds")
    if not config.heartbeat_interval * 3 < config.heartbeat_timeout <= 86400:
        parser.error("EDGE_SUPERVISOR_HEARTBEAT_TIMEOUT must exceed 3 heartbeat intervals and be <= 86400")
    if not 1 <= config.restart_base_seconds <= config.restart_max_seconds <= 3600:
        parser.error("restart backoff must satisfy 1 <= base <= max <= 3600")
    if not 1 <= config.shutdown_timeout <= 120:
        parser.error("shutdown timeout must be between 1 and 120 seconds")
    if args.healthcheck:
        return 0 if healthcheck(
            config.state_path, config.child_heartbeat_path,
            heartbeat_timeout=config.heartbeat_timeout,
            supervisor_timeout=max(config.heartbeat_interval * 3, 10),
        ) else 1

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    lock_path = Path(os.getenv("EDGE_SUPERVISOR_LOCK_PATH", "/tmp/edge-supervisor.lock"))
    lock_descriptor = _acquire_singleton_lock(lock_path)
    if lock_descriptor is None:
        logger.error("Another Edge supervisor already owns the singleton lock")
        return 1

    stop_event = threading.Event()

    def request_shutdown(signum: int, _frame: Any) -> None:
        logger.info("Supervisor shutdown requested: signal=%s", signum)
        stop_event.set()

    previous_term = signal.signal(signal.SIGTERM, request_shutdown)
    previous_int = signal.signal(signal.SIGINT, request_shutdown)
    from app.edge_supervisor_events import AsyncSupervisorEventWriter
    event_writer = AsyncSupervisorEventWriter()
    event_writer.start()
    try:
        return run_supervisor(config, stop_event, event_sink=event_writer.emit)
    finally:
        event_writer.close(timeout=float(os.getenv("EDGE_SUPERVISOR_EVENT_FLUSH_SECONDS", "2")))
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        os.close(lock_descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
