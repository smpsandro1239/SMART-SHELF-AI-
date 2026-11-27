import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.edge_event_supervisor import (
    SupervisorConfig,
    calculate_backoff,
    child_heartbeat,
    healthcheck,
    run_supervisor,
)
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


def test_child_heartbeat_is_atomic_and_identifies_current_process(tmp_path):
    target = tmp_path / "child.json"
    child_heartbeat(target)
    value = json.loads(target.read_text(encoding="utf-8"))
    assert value["pid"] == os.getpid()
    assert value["heartbeat_at"] <= time.time()
    assert not list(tmp_path.glob("*.tmp"))


def test_supervisor_healthcheck_rejects_stale_heartbeat(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    child = tmp_path / "child.json"
    now = time.time()
    state.write_text(json.dumps({
        "status": "RUNNING", "heartbeat_at": now, "child_pid": os.getpid()
    }), encoding="utf-8")
    child.write_text(json.dumps({
        "pid": os.getpid(), "heartbeat_at": now - 121
    }), encoding="utf-8")
    assert not healthcheck(state, child, now=now, heartbeat_timeout=120)


def test_supervisor_healthcheck_requires_live_matching_child(tmp_path):
    state = tmp_path / "state.json"
    child = tmp_path / "child.json"
    now = time.time()
    state.write_text(json.dumps({
        "status": "RUNNING", "heartbeat_at": now, "child_pid": os.getpid()
    }), encoding="utf-8")
    child.write_text(json.dumps({
        "pid": os.getpid() + 100000, "heartbeat_at": now
    }), encoding="utf-8")
    assert not healthcheck(state, child, now=now)


def test_restart_backoff_is_exponential_and_capped():
    assert calculate_backoff(0, 1, 8) == 0
    assert [calculate_backoff(i, 1, 8) for i in range(1, 6)] == [1, 2, 4, 8, 8]


def test_supervisor_restarts_crashed_child_and_stops_second_child(tmp_path):
    class FakeChild:
        def __init__(self, pid, return_code):
            self.pid = pid
            self.return_code = return_code
            self.terminated = False

        def poll(self):
            return self.return_code

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return self.return_code

        def kill(self):
            self.return_code = -9

    stop = threading.Event()
    children = []

    def spawn(_command, **_kwargs):
        child = FakeChild(os.getpid() + len(children) + 1, 17 if not children else None)
        children.append(child)
        if len(children) == 2:
            stop.set()
        return child

    config = SupervisorConfig(
        worker_id="supervisor-test",
        poll_interval=0.5,
        lease_seconds=30,
        heartbeat_interval=0.5,
        heartbeat_timeout=10,
        restart_base_seconds=1,
        restart_max_seconds=2,
        shutdown_timeout=1,
        state_path=tmp_path / "state.json",
        child_heartbeat_path=tmp_path / "child.json",
    )
    result = run_supervisor(config, stop, popen_factory=spawn)
    state = json.loads(config.state_path.read_text(encoding="utf-8"))
    assert result == 0
    assert len(children) == 2
    assert children[0].return_code == 17
    assert state["status"] == "STOPPED"
    assert state["restart_count"] == 1


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


def test_supervisor_entrypoint_exposes_healthcheck():
    api_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "app.edge_event_supervisor", "--help"],
        cwd=api_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "--healthcheck" in result.stdout
