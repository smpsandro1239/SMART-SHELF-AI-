import threading

from app.edge_event_worker_runtime import run_worker


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


def test_runtime_once_returns_failure_when_polling_raises():
    stop_event = threading.Event()

    def fail_poll(_factory, **_kwargs):
        raise RuntimeError("sensitive connection detail")

    result = run_worker(
        worker_id="edge-runtime-once",
        poll_interval=1,
        lease_seconds=30,
        stop_event=stop_event,
        process_event=fail_poll,
        once=True,
    )

    assert result == 1
