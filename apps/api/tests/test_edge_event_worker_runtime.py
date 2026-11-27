import subprocess
import sys
import threading
from pathlib import Path

from app.edge_event_worker import run_worker


def test_runtime_processes_one_event_and_stops_after_shutdown_request():
    stop_event = threading.Event()
    calls = []

    def process_event(_factory, *, worker_id, lease_seconds):
        calls.append((worker_id, lease_seconds))
        stop_event.set()
        return True

    result = run_worker(
        worker_id="edge-runtime-test",
        poll_interval=0.5,
        lease_seconds=30,
        stop_event=stop_event,
        process_event=process_event,
    )

    assert result == 0
    assert calls == [("edge-runtime-test", 30)]


def test_runtime_waits_when_queue_is_idle_and_shutdown_is_requested():
    stop_event = threading.Event()
    calls = []

    def process_event(_factory, **_kwargs):
        calls.append(True)
        stop_event.set()
        return False

    result = run_worker(
        worker_id="edge-runtime-idle",
        poll_interval=0.5,
        lease_seconds=30,
        stop_event=stop_event,
        process_event=process_event,
    )

    assert result == 0
    assert calls == [True]


def test_runtime_once_returns_failure_when_polling_raises(caplog):
    stop_event = threading.Event()
    sensitive_detail = "sensitive connection detail"

    def fail_poll(_factory, **_kwargs):
        raise RuntimeError(sensitive_detail)

    result = run_worker(
        worker_id="edge-runtime-once",
        poll_interval=1,
        lease_seconds=30,
        stop_event=stop_event,
        process_event=fail_poll,
        once=True,
    )

    assert result == 1
    assert sensitive_detail not in caplog.text


def test_module_entrypoint_loads_and_exposes_cli_help():
    api_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "app.edge_event_worker", "--help"],
        cwd=api_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "--poll-interval" in result.stdout
    assert "--lease-seconds" in result.stdout
    assert "--once" in result.stdout
