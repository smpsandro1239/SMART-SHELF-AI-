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
