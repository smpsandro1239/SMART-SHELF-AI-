import hashlib
import json

from app.dataset_approval import run_release_gate, validate_release_record


def make_document(prefix):
    return {
        "images": [
            {
                "id": 1,
                "file_name": f"{prefix}/shelf.jpg",
                "width": 100,
                "height": 100,
                "sha256": hashlib.sha256(f"{prefix}".encode()).hexdigest(),
                "file_size_bytes": 10,
                "capture_group_id": f"{prefix}-session",
            }
        ],
        "annotations": [
            {
                "id": 1,
                "image_id": 1,
                "category_id": 0,
                "bbox": [10, 10, 20, 20],
                "area": 400,
                "iscrowd": 0,
            }
        ],
        "categories": [{"id": 0, "name": "product"}],
    }


def make_record(manifest_hash):
    return {
        "dataset": {
            "name": "Retail shelf dataset",
            "version": "1.0.0",
            "created_at": "2026-11-12T10:00:00Z",
            "responsible": "Dataset owner",
            "manifest_sha256": manifest_hash,
            "storage_location": "Private controlled storage",
        },
        "purpose": {
            "task": "Object detection on retail shelves",
            "allowed_uses": ["Approved research and training"],
            "excluded_uses": ["Customer identification"],
        },
        "provenance": {
            "source_organizations": "Participating store with written authorization",
            "collection_authorized": True,
            "usage_rights": "Written authorization on file",
            "dataset_license": "Internal restricted use",
            "annotation_tool": "Annotation tool 1.0",
        },
        "privacy": {
            "exif_gps_removed": True,
            "personal_data_reviewed": True,
            "retention_and_access": "Restricted access and documented retention",
            "incident_review": "No unresolved incidents",
        },
        "quality": {
            "annotation_protocol": "Versioned annotation guide",
            "second_annotator_review_percent": 20,
            "quality_review_summary": "Sample reviewed and disagreements resolved",
        },
        "approvals": {
            "technical": {
                "reviewer": "Technical reviewer",
                "reviewed_at": "2026-11-12T11:00:00Z",
                "approved": True,
            },
            "privacy_legal": {
                "reviewer": "Privacy reviewer",
                "reviewed_at": "2026-11-12T11:30:00Z",
                "approved": True,
            },
        },
        "approved_for_training": True,
    }


def write_dataset(tmp_path):
    import csv

    paths = {}
    rows = []
    documents = {}
    for split in ("train", "val", "test"):
        image = f"{split}/shelf.jpg"
        content = split.encode()
        digest = hashlib.sha256(content).hexdigest()
        rows.append({
            "split": split,
            "file_name": image,
            "size_bytes": len(content),
            "sha256": digest,
        })
        document = make_document(split)
        document["images"][0]["sha256"] = digest
        document["images"][0]["file_size_bytes"] = len(content)
        documents[split] = document
        path = tmp_path / f"{split}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        paths[split] = path

    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["split", "file_name", "size_bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)
    return manifest, paths


def test_release_record_requires_explicit_approvals():
    record = make_record("a" * 64)
    assert validate_release_record(record) == []
    record["approvals"]["privacy_legal"]["approved"] = False
    assert any("explicit approval" in error for error in validate_release_record(record))


def test_training_gate_passes_only_when_manifest_and_audits_match(tmp_path):
    manifest, paths = write_dataset(tmp_path)
    record = make_record(hashlib.sha256(manifest.read_bytes()).hexdigest())
    errors, report = run_release_gate(record, manifest, paths)
    assert errors == []
    assert report["status"] == "APPROVED"
    assert report["checks"]["manifest_coco_integrity"]["passed"] is True


def test_manifest_hash_mismatch_blocks_release(tmp_path):
    manifest, paths = write_dataset(tmp_path)
    record = make_record("0" * 64)
    errors, report = run_release_gate(record, manifest, paths)
    assert any("does not match" in error for error in errors)
    assert report["status"] == "BLOCKED"


def test_missing_authorization_and_privacy_review_block_release():
    record = make_record("a" * 64)
    record["provenance"]["collection_authorized"] = False
    record["privacy"]["exif_gps_removed"] = False
    errors = validate_release_record(record)
    assert any("collection_authorized" in error for error in errors)
    assert any("exif_gps_removed" in error for error in errors)


def test_inference_gate_requires_model_metrics():
    record = make_record("a" * 64)
    errors = validate_release_record(record, mode="inference")
    assert any("approved_for_operational_inference" in error for error in errors)
    assert any("approvals.operational_inference" in error for error in errors)
    assert any("model.metrics_by_class" in error for error in errors)


def test_inference_gate_rejects_unmeasured_metric_values():
    record = make_record("a" * 64)
    record.update({
        "approved_for_operational_inference": True,
        "model": {
            "name": "Detector",
            "version": "1.0",
            "weights_license": "Apache-2.0",
            "evaluation_protocol": "Held-out test split",
            "metrics_by_class": {
                "product": {"precision": 0.9, "recall": None, "ap50": 0.8}
            },
        },
    })
    errors = validate_release_record(record, mode="inference")
    assert any("product.recall" in error for error in errors)


def write_approved_visual_reviews(tmp_path, paths):
    import copy
    from app.dataset_review import create_review_template

    review_paths = {}
    for split, coco_path in paths.items():
        document = json.loads(coco_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(coco_path.read_bytes()).hexdigest()
        record, errors = create_review_template(document, split, digest)
        assert errors == []
        for item in record["reviews"]:
            item.update({
                "decision": "APPROVED",
                "reviewer": "Human reviewer",
                "reviewed_at": "2026-11-12T12:00:00Z",
                "notes": "Reviewed visually",
            })
        review_path = tmp_path / f"{split}-review.json"
        review_path.write_text(json.dumps(record), encoding="utf-8")
        review_paths[split] = review_path
    return review_paths


def test_release_gate_can_require_complete_visual_reviews(tmp_path):
    manifest, paths = write_dataset(tmp_path)
    record = make_record(hashlib.sha256(manifest.read_bytes()).hexdigest())
    reviews = write_approved_visual_reviews(tmp_path, paths)

    errors, report = run_release_gate(
        record, manifest, paths, review_paths=reviews, require_visual_review=True
    )

    assert errors == []
    assert report["status"] == "APPROVED"
    assert report["checks"]["visual_review"]["passed"] is True


def test_release_gate_blocks_when_required_visual_reviews_are_missing(tmp_path):
    manifest, paths = write_dataset(tmp_path)
    record = make_record(hashlib.sha256(manifest.read_bytes()).hexdigest())

    errors, report = run_release_gate(
        record, manifest, paths, require_visual_review=True
    )

    assert any("visual review records are required" in error for error in errors)
    assert report["status"] == "BLOCKED"


def test_release_gate_detects_stale_visual_review_after_coco_change(tmp_path):
    manifest, paths = write_dataset(tmp_path)
    record = make_record(hashlib.sha256(manifest.read_bytes()).hexdigest())
    reviews = write_approved_visual_reviews(tmp_path, paths)

    document = json.loads(paths["train"].read_text(encoding="utf-8"))
    document["annotations"][0]["bbox"] = [11, 10, 20, 20]
    paths["train"].write_text(json.dumps(document), encoding="utf-8")

    errors, report = run_release_gate(
        record, manifest, paths, review_paths=reviews, require_visual_review=True
    )

    assert report["status"] == "BLOCKED"
    assert any("different COCO file hash" in error for error in errors)
    assert any("annotations changed since review" in error for error in errors)
