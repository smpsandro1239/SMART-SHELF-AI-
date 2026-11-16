import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import dataset_execution


def test_internal_consumer_runs_before_transaction_is_released(tmp_path, monkeypatch):
    provenance = tmp_path / "provenance.json"
    provenance.write_text(json.dumps({
        "schema_version": 1,
        "images": [{"source_type": "internal"}],
    }), encoding="utf-8")
    release_dir = tmp_path / "registry" / "releases"
    release_dir.mkdir(parents=True)
    release = {
        "release_id": "ds-123",
        "fingerprint": "a" * 64,
    }
    release_path = release_dir / f"{release['fingerprint']}.json"
    release_path.write_text(json.dumps(release), encoding="utf-8")

    events = []

    class FakeSession:
        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    monkeypatch.setattr(
        dataset_execution,
        "create_release",
        lambda *args, **kwargs: (events.append("release") or release, True),
    )
    monkeypatch.setattr(
        "app.database.SessionLocal",
        lambda: (events.append("open") or FakeSession()),
    )

    def fake_run(command, **kwargs):
        events.append("consumer")
        assert kwargs["shell"] is False
        assert kwargs["env"]["SMART_SHELF_DATASET_RELEASE_FINGERPRINT"] == "a" * 64
        assert Path(kwargs["env"]["SMART_SHELF_DATASET_RELEASE_PATH"]).is_file()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dataset_execution.subprocess, "run", fake_run)

    result = dataset_execution.run_release_consumer(
        tmp_path / "manifest.csv",
        tmp_path / "split.json",
        tmp_path / "visual.json",
        provenance,
        tmp_path / "registry",
        ["trainer", "--epochs", "1"],
    )

    assert result == 0
    assert events == ["open", "release", "consumer", "rollback", "close"]


def test_external_only_consumer_does_not_open_database(tmp_path, monkeypatch):
    provenance = tmp_path / "provenance.json"
    provenance.write_text(json.dumps({
        "schema_version": 1,
        "images": [{"source_type": "external"}],
    }), encoding="utf-8")
    release_dir = tmp_path / "registry" / "releases"
    release_dir.mkdir(parents=True)
    release = {"release_id": "ds-456", "fingerprint": "b" * 64}
    (release_dir / f"{release['fingerprint']}.json").write_text(
        json.dumps(release), encoding="utf-8"
    )

    monkeypatch.setattr(
        dataset_execution,
        "create_release",
        lambda *args, **kwargs: (release, False),
    )
    monkeypatch.setattr(
        dataset_execution.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=7),
    )

    assert dataset_execution.run_release_consumer(
        tmp_path / "manifest.csv",
        tmp_path / "split.json",
        tmp_path / "visual.json",
        provenance,
        tmp_path / "registry",
        ["trainer"],
    ) == 7


@pytest.mark.parametrize("command,timeout", [([], None), (["trainer"], 0), ([""], None)])
def test_consumer_rejects_invalid_command_or_timeout(
    tmp_path, command, timeout
):
    provenance = tmp_path / "provenance.json"
    provenance.write_text(json.dumps({
        "schema_version": 1,
        "images": [{"source_type": "external"}],
    }), encoding="utf-8")
    with pytest.raises(ValueError):
        dataset_execution.run_release_consumer(
            tmp_path / "manifest.csv",
            tmp_path / "split.json",
            tmp_path / "visual.json",
            provenance,
            tmp_path / "registry",
            command,
            timeout_seconds=timeout,
        )


def test_consumer_rejects_malformed_provenance_before_execution(tmp_path):
    provenance = tmp_path / "provenance.json"
    provenance.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="images array"):
        dataset_execution.run_release_consumer(
            tmp_path / "manifest.csv",
            tmp_path / "split.json",
            tmp_path / "visual.json",
            provenance,
            tmp_path / "registry",
            ["trainer"],
        )
