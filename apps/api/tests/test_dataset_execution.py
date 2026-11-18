import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import dataset_execution


def write_inputs(tmp_path, source_type="internal"):
    provenance = tmp_path / "provenance.json"
    provenance.write_text(json.dumps({
        "schema_version": 1,
        "images": [{"source_type": source_type}],
    }), encoding="utf-8")
    release_record = tmp_path / "release-record.json"
    release_record.write_text(json.dumps({"approved_for_training": True}), encoding="utf-8")
    split_paths = {}
    for split in ("train", "val", "test"):
        path = tmp_path / f"{split}.json"
        path.write_text("{}", encoding="utf-8")
        split_paths[split] = path
    return provenance, release_record, split_paths


def fake_release(tmp_path):
    release_dir = tmp_path / "registry" / "releases"
    release_dir.mkdir(parents=True)
    release = {"release_id": "ds-123", "fingerprint": "a" * 64}
    (release_dir / f"{release['fingerprint']}.json").write_text(json.dumps(release), encoding="utf-8")
    return release


def test_internal_consumer_runs_only_after_approval_and_before_source_locks_release(tmp_path, monkeypatch):
    provenance, record, splits = write_inputs(tmp_path)
    release = fake_release(tmp_path)
    events = []

    class FakeSession:
        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    monkeypatch.setattr("app.database.SessionLocal", lambda: (events.append("open") or FakeSession()))

    def fake_gate(*args, **kwargs):
        events.append("gate")
        assert kwargs["db_session"] is not None
        return [], {"status": "APPROVED", "checks": {"all": {"passed": True}}}

    def fake_create(*args, **kwargs):
        events.append("release")
        evidence = kwargs["approval_evidence"]
        assert evidence["status"] == "APPROVED"
        assert evidence["mode"] == "training"
        assert len(evidence["record_sha256"]) == 64
        assert len(evidence["gate_report_sha256"]) == 64
        return release, True

    monkeypatch.setattr("app.dataset_approval.run_release_gate", fake_gate)
    monkeypatch.setattr(dataset_execution, "create_release", fake_create)

    def fake_run(command, **kwargs):
        events.append("consumer")
        env = kwargs["env"]
        assert kwargs["shell"] is False
        assert env["SMART_SHELF_DATASET_RELEASE_FINGERPRINT"] == "a" * 64
        assert env["SMART_SHELF_DATASET_APPROVAL_STATUS"] == "APPROVED"
        assert env["SMART_SHELF_DATASET_APPROVAL_MODE"] == "training"
        assert env["SMART_SHELF_DATASET_APPROVAL_RECORD_SHA256"]
        assert env["SMART_SHELF_DATASET_APPROVAL_REPORT_SHA256"]
        assert Path(env["SMART_SHELF_DATASET_RELEASE_PATH"]).is_file()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dataset_execution.subprocess, "run", fake_run)
    result = dataset_execution.run_release_consumer(
        tmp_path / "manifest.csv", tmp_path / "split.json", tmp_path / "visual.json",
        provenance, tmp_path / "registry", ["trainer", "--epochs", "1"],
        release_record_path=record, split_paths=splits,
    )
    assert result == 0
    assert events == ["open", "gate", "release", "consumer", "rollback", "close"]


def test_external_only_consumer_does_not_open_database(tmp_path, monkeypatch):
    provenance, record, splits = write_inputs(tmp_path, source_type="external")
    release = fake_release(tmp_path)
    events = []

    def fake_gate(*args, **kwargs):
        events.append("gate")
        assert kwargs["db_session"] is None
        return [], {"status": "APPROVED"}

    monkeypatch.setattr("app.dataset_approval.run_release_gate", fake_gate)
    monkeypatch.setattr(dataset_execution, "create_release",
                        lambda *args, **kwargs: (events.append("release") or (release, False)))
    monkeypatch.setattr(dataset_execution.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=7))
    result = dataset_execution.run_release_consumer(
        tmp_path / "manifest.csv", tmp_path / "split.json", tmp_path / "visual.json",
        provenance, tmp_path / "registry", ["trainer"],
        release_record_path=record, split_paths=splits,
    )
    assert result == 7
    assert events == ["gate", "release"]


def test_rejected_approval_never_creates_release_or_starts_consumer(tmp_path, monkeypatch):
    provenance, record, splits = write_inputs(tmp_path)
    events = []

    class FakeSession:
        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    monkeypatch.setattr("app.database.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("app.dataset_approval.run_release_gate",
                        lambda *args, **kwargs: (["privacy approval missing"], {"status": "BLOCKED"}))
    monkeypatch.setattr(dataset_execution, "create_release",
                        lambda *args, **kwargs: pytest.fail("release must not be created after a rejected gate"))
    monkeypatch.setattr(dataset_execution.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("consumer must not start after a rejected gate"))

    with pytest.raises(ValueError, match="dataset approval gate rejected"):
        dataset_execution.run_release_consumer(
            tmp_path / "manifest.csv", tmp_path / "split.json", tmp_path / "visual.json",
            provenance, tmp_path / "registry", ["trainer"],
            release_record_path=record, split_paths=splits,
        )
    assert events == ["rollback", "close"]


@pytest.mark.parametrize("command,timeout", [([], None), (["trainer"], 0), ([""], None)])
def test_consumer_rejects_invalid_command_or_timeout(tmp_path, command, timeout):
    provenance, record, splits = write_inputs(tmp_path, source_type="external")
    with pytest.raises(ValueError):
        dataset_execution.run_release_consumer(
            tmp_path / "manifest.csv", tmp_path / "split.json", tmp_path / "visual.json",
            provenance, tmp_path / "registry", command,
            release_record_path=record, split_paths=splits, timeout_seconds=timeout,
        )


def test_consumer_rejects_malformed_provenance_before_execution(tmp_path, monkeypatch):
    provenance = tmp_path / "provenance.json"
    provenance.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(dataset_execution.subprocess, "run",
                        lambda *args, **kwargs: pytest.fail("consumer must not run"))
    with pytest.raises(ValueError, match="images array"):
        dataset_execution.run_release_consumer(
            tmp_path / "manifest.csv", tmp_path / "split.json", tmp_path / "visual.json",
            provenance, tmp_path / "registry", ["trainer"],
            release_record_path=tmp_path / "release.json",
            split_paths={"train": tmp_path / "train.json", "val": tmp_path / "val.json", "test": tmp_path / "test.json"},
        )
