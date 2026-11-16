from app.dataset_provenance import validate_provenance_manifest


def digest(char):
    return char * 64


def manifest_row(split="train", name="shelf.jpg", sha=None):
    return {
        "split": split,
        "file_name": name,
        "size_bytes": "10",
        "sha256": sha or digest("a"),
    }


def internal_entry():
    return {
        "split": "train",
        "file_name": "shelf.jpg",
        "image_sha256": digest("a"),
        "source_type": "internal",
        "shelf_image_id": 42,
        "store_id": 7,
        "source_image_sha256": digest("b"),
        "purpose": "Approved product detection training",
        "transformation": {"type": "crop", "parent_sha256": digest("b"), "operation": "shelf-region crop v1"},
    }


def external_entry():
    return {
        "split": "train",
        "file_name": "shelf.jpg",
        "image_sha256": digest("a"),
        "source_image_sha256": digest("a"),
        "source_type": "external",
        "source_name": "Licensed retail dataset",
        "license": "CC-BY-4.0",
        "rights_reference": "licence-record-2026-01",
        "purpose": "Approved product detection training",
        "transformation": {"type": "original"},
    }


def test_provenance_accepts_internal_capture_with_store_and_lineage():
    errors, report = validate_provenance_manifest(
        {"schema_version": 1, "images": [internal_entry()]},
        [manifest_row()],
    )
    assert errors == []
    assert report["status"] == "APPROVED"


def test_provenance_accepts_external_image_with_license_reference():
    errors, report = validate_provenance_manifest(
        {"schema_version": 1, "images": [external_entry()]},
        [manifest_row()],
    )
    assert errors == []
    assert report["status"] == "APPROVED"


def test_provenance_requires_exact_manifest_coverage_and_hash_match():
    entry = internal_entry()
    entry["image_sha256"] = digest("c")
    errors, report = validate_provenance_manifest(
        {"schema_version": 1, "images": [entry]},
        [manifest_row()],
    )
    assert any("does not match manifest" in error for error in errors)
    assert report["status"] == "BLOCKED"


def test_internal_provenance_requires_positive_source_and_store_ids():
    entry = internal_entry()
    entry["shelf_image_id"] = True
    entry["store_id"] = 0
    errors, _ = validate_provenance_manifest(
        {"schema_version": 1, "images": [entry]},
        [manifest_row()],
    )
    assert any("shelf_image_id must be a positive integer" in error for error in errors)
    assert any("store_id must be a positive integer" in error for error in errors)


def test_external_provenance_requires_license_and_rights_reference():
    entry = external_entry()
    entry.pop("license")
    entry["rights_reference"] = " "
    errors, _ = validate_provenance_manifest(
        {"schema_version": 1, "images": [entry]},
        [manifest_row()],
    )
    assert any(".license is required" in error for error in errors)
    assert any(".rights_reference is required" in error for error in errors)


def test_derived_image_requires_parent_hash_and_operation():
    entry = external_entry()
    entry["transformation"] = {"type": "crop", "operation": ""}
    errors, _ = validate_provenance_manifest(
        {"schema_version": 1, "images": [entry]},
        [manifest_row()],
    )
    assert any("parent_sha256 is required" in error for error in errors)
    assert any("operation is required" in error for error in errors)


def test_provenance_rejects_duplicate_or_unmatched_entries():
    entry = internal_entry()
    errors, _ = validate_provenance_manifest(
        {"schema_version": 1, "images": [entry, dict(entry)]},
        [manifest_row()],
    )
    assert any("duplicate provenance entry" in error for error in errors)

    entry["file_name"] = "not-in-manifest.jpg"
    errors, _ = validate_provenance_manifest(
        {"schema_version": 1, "images": [entry]},
        [manifest_row()],
    )
    assert any("absent from the SHA-256 manifest" in error for error in errors)
    assert any("missing provenance entry" in error for error in errors)


def test_provenance_rejects_mixed_internal_and_external_fields():
    entry = internal_entry()
    entry["license"] = "unknown"
    errors, _ = validate_provenance_manifest(
        {"schema_version": 1, "images": [entry]},
        [manifest_row()],
    )
    assert any("license is not applicable to internal images" in error for error in errors)


def test_original_image_hash_must_match_declared_source_hash():
    entry = external_entry()
    entry["source_image_sha256"] = digest("b")
    errors, _ = validate_provenance_manifest(
        {"schema_version": 1, "images": [entry]},
        [manifest_row()],
    )
    assert any("original image hash must equal source_image_sha256" in error for error in errors)


def test_crop_parent_must_match_declared_source_hash():
    entry = internal_entry()
    entry["transformation"]["parent_sha256"] = digest("c")
    errors, _ = validate_provenance_manifest(
        {"schema_version": 1, "images": [entry]},
        [manifest_row()],
    )
    assert any("parent_sha256 must match source_image_sha256" in error for error in errors)


def test_provenance_validator_reports_unhashable_json_values_without_crashing():
    entry = external_entry()
    entry["source_type"] = ["external"]
    entry["transformation"]["type"] = {"kind": "original"}
    errors, report = validate_provenance_manifest(
        {"schema_version": 1, "images": [entry]},
        [manifest_row()],
    )
    assert any("source_type must be internal or external" in error for error in errors)
    assert any("transformation.type must be original, crop or derived" in error for error in errors)
    assert report["status"] == "BLOCKED"


def test_derived_parent_reference_resolves_hash_and_source_identity():
    parent = external_entry()
    parent["file_name"] = "original.jpg"
    child = external_entry()
    child["file_name"] = "crop.jpg"
    child["image_sha256"] = digest("c")
    child["source_image_sha256"] = digest("a")
    child["transformation"] = {
        "type": "crop",
        "parent_sha256": digest("a"),
        "parent_split": "train",
        "parent_file_name": "original.jpg",
        "operation": "crop v2",
    }
    rows = [
        manifest_row(name="original.jpg", sha=digest("a")),
        manifest_row(name="crop.jpg", sha=digest("c")),
    ]
    errors, report = validate_provenance_manifest(
        {"schema_version": 1, "images": [child, parent]}, rows
    )
    assert errors == []
    assert report["status"] == "APPROVED"


def test_derived_parent_reference_rejects_missing_or_mismatched_parent():
    child = external_entry()
    child["transformation"] = {
        "type": "derived",
        "parent_sha256": digest("b"),
        "parent_split": "train",
        "parent_file_name": "missing.jpg",
        "operation": "resize v1",
    }
    errors, _ = validate_provenance_manifest(
        {"schema_version": 1, "images": [child]}, [manifest_row()]
    )
    assert any("declared parent is absent" in error for error in errors)


def test_derived_parent_reference_rejects_cycles():
    first = external_entry()
    first["file_name"] = "first.jpg"
    first["image_sha256"] = digest("a")
    first["source_image_sha256"] = digest("b")
    first["transformation"] = {
        "type": "derived", "parent_sha256": digest("b"),
        "parent_split": "train", "parent_file_name": "second.jpg",
        "operation": "transform first",
    }
    second = external_entry()
    second["file_name"] = "second.jpg"
    second["image_sha256"] = digest("b")
    second["source_image_sha256"] = digest("a")
    second["transformation"] = {
        "type": "derived", "parent_sha256": digest("a"),
        "parent_split": "train", "parent_file_name": "first.jpg",
        "operation": "transform second",
    }
    rows = [
        manifest_row(name="first.jpg", sha=digest("a")),
        manifest_row(name="second.jpg", sha=digest("b")),
    ]
    errors, _ = validate_provenance_manifest(
        {"schema_version": 1, "images": [first, second]}, rows
    )
    assert any("cyclic derivative lineage" in error for error in errors)
