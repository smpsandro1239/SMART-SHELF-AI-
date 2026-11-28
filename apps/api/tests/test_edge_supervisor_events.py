"""Focused tests for the asynchronous, best-effort supervisor event writer."""
from __future__ import annotations

import threading

from app.edge_supervisor_events import AsyncSupervisorEventWriter


class _FakeSession:
    def __init__(self, *, on_commit=None):
        self.on_commit = on_commit
        self.pending = []
        self.committed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def add(self, item):
        self.pending.append(item)

    def commit(self):
        if self.on_commit is not None:
            self.on_commit(self)
        self.committed.extend(self.pending)
        self.pending.clear()

    def rollback(self):
        self.pending.clear()


def test_writer_persists_allowlisted_event_and_gracefully_drains_queue():
    persisted = []
    writer = AsyncSupervisorEventWriter(
        lambda: _FakeSession(on_commit=lambda session: persisted.extend(session.pending))
    )
    writer.start()

    assert writer.emit(
        event_type="RESTARTING",
        supervisor_instance_id="supervisor-test",
        worker_id="worker-test",
        reason_code="CHILD_EXITED",
        restart_count=2,
        exit_code=1,
    )

    writer.close(timeout=5)

    assert writer._thread is not None
    assert not writer._thread.is_alive()
    assert len(persisted) == 1
    assert persisted[0].event_type == "RESTARTING"
    assert persisted[0].reason_code == "CHILD_EXITED"
    assert persisted[0].restart_count == 2
    assert persisted[0].exit_code == 1
    assert not hasattr(persisted[0], "payload")


def test_writer_rejects_events_outside_allowlist():
    writer = AsyncSupervisorEventWriter(lambda: _FakeSession())
    writer.start()

    assert not writer.emit(
        event_type="UNSAFE_EVENT",
        supervisor_instance_id="supervisor-test",
        worker_id="worker-test",
    )
    assert not writer.emit(
        event_type="STARTED",
        supervisor_instance_id="supervisor-test",
        worker_id="worker-test",
        reason_code="RAW_EXCEPTION_TEXT",
    )

    writer.close(timeout=5)


def test_queue_saturation_drops_observability_event_without_blocking_supervisor():
    database_entered = threading.Event()
    release_database = threading.Event()
    persisted = []

    def session_factory():
        def block_first_commit(session):
            if not database_entered.is_set():
                database_entered.set()
                assert release_database.wait(timeout=5)
            persisted.extend(session.pending)

        return _FakeSession(on_commit=block_first_commit)

    writer = AsyncSupervisorEventWriter(session_factory, max_queue_size=1)
    writer.start()
    event = {
        "event_type": "STARTED",
        "supervisor_instance_id": "supervisor-test",
        "worker_id": "worker-test",
    }

    assert writer.emit(**event)
    assert database_entered.wait(timeout=5)
    assert writer.emit(**event)  # Occupies the one waiting queue slot.

    # put_nowait is the contract: saturation must not wait for the database.
    assert not writer.emit(**event)

    release_database.set()
    writer.close(timeout=5)

    assert writer._thread is not None and not writer._thread.is_alive()
    assert len(persisted) == 2


def test_database_failure_is_best_effort_and_writer_continues():
    persisted = []
    attempts = 0

    def session_factory():
        def fail_first_commit(session):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("database unavailable")
            persisted.extend(session.pending)

        return _FakeSession(on_commit=fail_first_commit)

    writer = AsyncSupervisorEventWriter(session_factory)
    writer.start()
    for _ in range(2):
        assert writer.emit(
            event_type="CHILD_EXITED",
            supervisor_instance_id="supervisor-test",
            worker_id="worker-test",
            reason_code="CHILD_EXITED",
            exit_code=1,
        )

    writer.close(timeout=5)

    assert attempts == 2
    assert len(persisted) == 1
    assert persisted[0].event_type == "CHILD_EXITED"
