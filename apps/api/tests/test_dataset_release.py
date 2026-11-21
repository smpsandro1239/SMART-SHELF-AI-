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
    from app.dataset_release import load_manifest

    rows = load_manifest(manifest)
    provenance = tmp_path / "provenance.json"
    entries = [{
        "split": row["split"],
        "file_name": row["file_name"],
        "image_sha256": row["sha256"],
        "source_image_sha256": row["sha256"],
        "source_type": "external",
        "source_name": "Test licensed dataset",
        "license": "CC-BY-4.0",
        "rights_reference": "test-rights-record",
        "purpose": "Product detection training",
        "transformation": {"type": "original"},
    } for row in rows]
    provenance.write_text(
        json.dumps({"schema_version": 1, "images": entries}),
        encoding="utf-8",
    )
    return manifest, split, visual, provenance


def test_release_is_created_with_deterministic_fingerprint_and_quality_metadata(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    release, created = create_release(manifest, split, visual, tmp_path / "registry", provenance_path=provenance)
    assert created is True
    assert release["image_count"] == 3
    assert release["images_by_split"] == {"test": 1, "train": 1, "val": 1}
    assert release["quality_gates"]["split_integrity"]["status"] == "passed"
    assert release["class_balance"]["by_split"]["train"]["classes"]["1"]["instances"] == 4
    assert release["class_balance"]["instances_by_class_and_split"]["1"]["train"] == 4
    assert (tmp_path / "registry" / "releases" / f"{release['fingerprint']}.json").is_file()


def test_release_creation_is_idempotent(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    registry = tmp_path / "registry"
    first, created_first = create_release(manifest, split, visual, registry, provenance_path=provenance)
    second, created_second = create_release(manifest, split, visual, registry, provenance_path=provenance)
    assert created_first is True
    assert created_second is False
    assert first["fingerprint"] == second["fingerprint"]


def test_release_rejects_failed_split_quality_gate(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    write_report(split, status="failed", errors=["capture session leaked"])
    with pytest.raises(ValueError, match="split audit quality gate"):
        create_release(manifest, split, visual, tmp_path / "registry", provenance_path=provenance)


def test_release_rejects_failed_visual_quality_gate(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    write_report(visual, status="failed", errors=["near duplicate across splits"])
    with pytest.raises(ValueError, match="visual similarity audit quality gate"):
        create_release(manifest, split, visual, tmp_path / "registry", provenance_path=provenance)


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
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    write_report(split, splits={
        "train": {"classes": {"1": {"name": "soda", "instances": 10}}},
        "val": {"classes": {"1": {"name": "soda", "instances": 2}}},
        "test": {"classes": {"1": {"name": "soda", "instances": 0}}},
    })
    release, _ = create_release(manifest, split, visual, tmp_path / "registry", provenance_path=provenance)
    assert "class 1 has no annotated instances in test" in release["class_balance"]["warnings"]
    assert release["class_balance"]["instances_by_class_and_split"]["1"]["val"] == 2


def test_release_can_enforce_minimum_class_instances_per_split(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    write_report(split, splits={
        "train": {"classes": {"1": {"instances": 10}}},
        "val": {"classes": {"1": {"instances": 2}}},
        "test": {"classes": {"1": {"instances": 1}}},
    })
    with pytest.raises(ValueError, match="minimum is 3"):
        create_release(
            manifest, split, visual, tmp_path / "registry",
            provenance_path=provenance,
            min_class_instances=3,
        )


def test_release_can_enforce_minimum_images_per_split(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    with pytest.raises(ValueError, match="minimum is 2"):
        create_release(
            manifest, split, visual, tmp_path / "registry",
            provenance_path=provenance,
            min_images_per_split=2,
        )

def test_release_requires_complete_provenance_sidecar(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    provenance.write_text(json.dumps({"schema_version": 1, "images": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance manifest rejected"):
        create_release(manifest, split, visual, tmp_path / "registry", provenance_path=provenance)


def test_release_blocks_internal_provenance_without_operational_database(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    record = json.loads(provenance.read_text(encoding="utf-8"))
    for entry in record["images"]:
        entry.update({"source_type": "internal", "shelf_image_id": 1, "store_id": 1})
        for field in ("source_name", "license", "rights_reference"):
            entry.pop(field, None)
    provenance.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="database session is required"):
        create_release(manifest, split, visual, tmp_path / "registry", provenance_path=provenance)


def test_release_records_provenance_and_operational_eligibility_hashes(tmp_path):
    import hashlib
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    release, created = create_release(manifest, split, visual, tmp_path / "registry", provenance_path=provenance)
    assert created is True
    assert release["provenance"]["status"] == "APPROVED"
    assert release["provenance"]["manifest_sha256"] == hashlib.sha256(provenance.read_bytes()).hexdigest()
    assert release["provenance"]["operational_eligibility"] == {"status": "APPROVED", "internal_images": 0, "checked_images": 0}



def test_release_registry_rejects_modified_existing_metadata(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    registry = tmp_path / "registry"
    release, created = create_release(
        manifest, split, visual, registry, provenance_path=provenance
    )
    assert created is True
    destination = registry / "releases" / f"{release['fingerprint']}.json"
    tampered = json.loads(destination.read_text(encoding="utf-8"))
    tampered["image_count"] = 999
    destination.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(RuntimeError, match="existing release metadata differs"):
        create_release(
            manifest, split, visual, registry, provenance_path=provenance
        )


def test_release_registry_rejects_symlinked_release_record(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    registry = tmp_path / "registry"
    release, created = create_release(
        manifest, split, visual, registry, provenance_path=provenance
    )
    assert created is True
    destination = registry / "releases" / f"{release['fingerprint']}.json"
    destination.unlink()
    external = tmp_path / "external-release.json"
    external.write_text("{}", encoding="utf-8")
    destination.symlink_to(external)

    with pytest.raises(RuntimeError, match="must not be a symlink"):
        create_release(
            manifest, split, visual, registry, provenance_path=provenance
        )


@pytest.mark.parametrize("file_name", [
    "..\\\\outside.jpg",
    "C:/outside.jpg",
    "C:\\\\outside.jpg",
    "//server/share/image.jpg",
    "folder/image.jpg:stream",
])
def test_release_manifest_rejects_non_portable_paths(tmp_path, file_name):
    path = tmp_path / "manifest.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["split", "file_name", "size_bytes", "sha256"])
        writer.writeheader()
        for split, name in [("train", file_name), ("val", "b.jpg"), ("test", "c.jpg")]:
            writer.writerow({"split": split, "file_name": name, "size_bytes": 1, "sha256": "a" * 64})
    with pytest.raises(ValueError, match="unsafe file_name"):
        load_manifest(path)



def test_approval_evidence_is_bound_to_release_fingerprint(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    registry = tmp_path / "registry"
    approval_one = {
        "status": "APPROVED", "mode": "training",
        "record_sha256": "a" * 64, "gate_report_sha256": "b" * 64,
        "split_annotations_sha256": {"train": "1" * 64, "val": "2" * 64, "test": "3" * 64},
    }
    approval_two = {
        "status": "APPROVED", "mode": "training",
        "record_sha256": "c" * 64, "gate_report_sha256": "b" * 64,
        "split_annotations_sha256": {"train": "1" * 64, "val": "2" * 64, "test": "4" * 64},
    }
    first, first_created = create_release(
        manifest, split, visual, registry,
        provenance_path=provenance, approval_evidence=approval_one,
    )
    second, second_created = create_release(
        manifest, split, visual, registry,
        provenance_path=provenance, approval_evidence=approval_two,
    )
    assert first_created is True
    assert second_created is True
    assert first["approval"] == approval_one
    assert second["approval"] == approval_two
    assert first["fingerprint"] != second["fingerprint"]


def test_release_rejects_malformed_approval_evidence(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    with pytest.raises(ValueError, match="record_sha256"):
        create_release(
            manifest, split, visual, tmp_path / "registry",
            provenance_path=provenance,
            approval_evidence={
                "status": "APPROVED", "mode": "training",
                "record_sha256": "not-a-digest", "gate_report_sha256": "b" * 64,
            },
        )


def test_release_rejects_incomplete_or_malformed_split_annotation_hashes(tmp_path):
    manifest, split, visual, provenance = setup_release_inputs(tmp_path)
    with pytest.raises(ValueError, match="must contain train, val and test"):
        create_release(
            manifest, split, visual, tmp_path / "registry",
            provenance_path=provenance,
            approval_evidence={
                "status": "APPROVED", "mode": "inference",
                "record_sha256": "a" * 64, "gate_report_sha256": "b" * 64,
                "split_annotations_sha256": {"test": "c" * 64},
            },
        )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        create_release(
            manifest, split, visual, tmp_path / "registry",
            provenance_path=provenance,
            approval_evidence={
                "status": "APPROVED", "mode": "inference",
                "record_sha256": "a" * 64, "gate_report_sha256": "b" * 64,
                "split_annotations_sha256": {"train": "a" * 64, "val": "b" * 64, "test": "bad"},
            },
        )
