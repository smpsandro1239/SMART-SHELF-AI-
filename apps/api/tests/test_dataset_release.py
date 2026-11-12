import csv
import json

import pytest

from app.dataset_release import create_release, load_manifest


def write_manifest(path):
    rows = [
        {"split": "train", "file_name": "a.jpg", "size_bytes": 10, "sha256": "a" * 64},
        {"split": "val", "file_name": "b.jpg", "size_bytes": 11, "sha256": "b" * 64},
        {"split": "test", "file_name": "c.jpg", "size_bytes": 12, "sha256": "c" * 64},
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["split", "file_name", "size_bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)


def write_report(path, **overrides):
    payload = {"status": "passed", "errors": [], "splits": {}, "cross_split": {}}
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


def setup_release_inputs(tmp_path):
    manifest = tmp_path / "manifest.csv"
    split = tmp_path / "split.json"
    visual = tmp_path / "visual.json"
    write_manifest(manifest)
    write_report(split, splits={"train": {"classes": {"1": {"instances": 4}}}})
    write_report(visual, algorithm="dHash-64", max_hamming_distance=6, images_scanned=3)
    return manifest, split, visual


def test_release_is_created_with_deterministic_fingerprint_and_quality_metadata(tmp_path):
    manifest, split, visual = setup_release_inputs(tmp_path)
    release, created = create_release(manifest, split, visual, tmp_path / "registry")
    assert created is True
    assert release["image_count"] == 3
    assert release["images_by_split"] == {"test": 1, "train": 1, "val": 1}
    assert release["quality_gates"]["split_integrity"]["status"] == "passed"
    assert release["class_balance"]["by_split"]["train"]["classes"]["1"]["instances"] == 4
    assert release["class_balance"]["instances_by_class_and_split"]["1"]["train"] == 4
    assert (tmp_path / "registry" / "releases" / f"{release['fingerprint']}.json").is_file()


def test_release_creation_is_idempotent(tmp_path):
    manifest, split, visual = setup_release_inputs(tmp_path)
    registry = tmp_path / "registry"
    first, created_first = create_release(manifest, split, visual, registry)
    second, created_second = create_release(manifest, split, visual, registry)
    assert created_first is True
    assert created_second is False
    assert first["fingerprint"] == second["fingerprint"]


def test_release_rejects_failed_split_quality_gate(tmp_path):
    manifest, split, visual = setup_release_inputs(tmp_path)
    write_report(split, status="failed", errors=["capture session leaked"])
    with pytest.raises(ValueError, match="split audit quality gate"):
        create_release(manifest, split, visual, tmp_path / "registry")


def test_release_rejects_failed_visual_quality_gate(tmp_path):
    manifest, split, visual = setup_release_inputs(tmp_path)
    write_report(visual, status="failed", errors=["near duplicate across splits"])
    with pytest.raises(ValueError, match="visual similarity audit quality gate"):
        create_release(manifest, split, visual, tmp_path / "registry")


def test_manifest_rejects_path_traversal(tmp_path):
    path = tmp_path / "manifest.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["split", "file_name", "size_bytes", "sha256"])
        writer.writeheader()
        for split, name in [("train", "../escape.jpg"), ("val", "b.jpg"), ("test", "c.jpg")]:
            writer.writerow({"split": split, "file_name": name, "size_bytes": 1, "sha256": "a" * 64})
    with pytest.raises(ValueError, match="unsafe file_name"):
        load_manifest(path)


def test_manifest_requires_all_three_splits(tmp_path):
    path = tmp_path / "manifest.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["split", "file_name", "size_bytes", "sha256"])
        writer.writeheader()
        writer.writerow({"split": "train", "file_name": "a.jpg", "size_bytes": 1, "sha256": "a" * 64})
    with pytest.raises(ValueError, match="missing split"):
        load_manifest(path)



def test_release_reports_classes_missing_from_a_split(tmp_path):
    manifest, split, visual = setup_release_inputs(tmp_path)
    write_report(split, splits={
        "train": {"classes": {"1": {"name": "soda", "instances": 10}}},
        "val": {"classes": {"1": {"name": "soda", "instances": 2}}},
        "test": {"classes": {"1": {"name": "soda", "instances": 0}}},
    })
    release, _ = create_release(manifest, split, visual, tmp_path / "registry")
    assert "class 1 has no annotated instances in test" in release["class_balance"]["warnings"]
    assert release["class_balance"]["instances_by_class_and_split"]["1"]["val"] == 2


def test_release_can_enforce_minimum_class_instances_per_split(tmp_path):
    manifest, split, visual = setup_release_inputs(tmp_path)
    write_report(split, splits={
        "train": {"classes": {"1": {"instances": 10}}},
        "val": {"classes": {"1": {"instances": 2}}},
        "test": {"classes": {"1": {"instances": 1}}},
    })
    with pytest.raises(ValueError, match="minimum is 3"):
        create_release(
            manifest, split, visual, tmp_path / "registry",
            min_class_instances=3,
        )


def test_release_can_enforce_minimum_images_per_split(tmp_path):
    manifest, split, visual = setup_release_inputs(tmp_path)
    with pytest.raises(ValueError, match="minimum is 2"):
        create_release(
            manifest, split, visual, tmp_path / "registry",
            min_images_per_split=2,
        )
