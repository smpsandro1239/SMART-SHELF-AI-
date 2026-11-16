import hashlib

from app.dataset_integrity import (
    audit_manifest_against_coco,
    enrich_coco_document,
    read_manifest,
)


def coco(file_name, sha256=None, size=None):
    image = {"id": 1, "file_name": file_name, "width": 100, "height": 80}
    if sha256 is not None:
        image["sha256"] = sha256
    if size is not None:
        image["file_size_bytes"] = size
    return {
        "images": [image],
        "annotations": [{
            "id": 1, "image_id": 1, "category_id": 0,
            "bbox": [10, 10, 20, 20], "area": 400, "iscrowd": 0,
        }],
        "categories": [{"id": 0, "name": "product"}],
    }


def row(split, name, content):
    return {
        "split": split,
        "file_name": name,
        "size_bytes": str(len(content)),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def splits(train=None, val=None, test=None):
    return {
        "train": train or {"images": [], "annotations": [], "categories": [{"id": 0, "name": "product"}]},
        "val": val or {"images": [], "annotations": [], "categories": [{"id": 0, "name": "product"}]},
        "test": test or {"images": [], "annotations": [], "categories": [{"id": 0, "name": "product"}]},
    }


def test_integrity_accepts_matching_manifest_and_coco():
    image_bytes = b"real-image-content"
    manifest = [row("train", "a.jpg", image_bytes)]
    documents = splits(train=coco("a.jpg", hashlib.sha256(image_bytes).hexdigest(), len(image_bytes)))
    assert audit_manifest_against_coco(manifest, documents) == []


def test_integrity_detects_coco_image_missing_from_manifest():
    errors = audit_manifest_against_coco([], splits(train=coco("missing.jpg")))
    assert any("missing from manifest" in error for error in errors)


def test_integrity_detects_manifest_image_missing_from_coco():
    errors = audit_manifest_against_coco([row("train", "extra.jpg", b"x")], splits())
    assert any("absent from COCO annotations" in error for error in errors)


def test_integrity_detects_wrong_split():
    manifest = [row("val", "same.jpg", b"x")]
    errors = audit_manifest_against_coco(manifest, splits(train=coco("same.jpg")))
    assert any("not train" in error for error in errors)


def test_integrity_detects_hash_and_size_mismatch():
    manifest = [row("train", "a.jpg", b"correct")]
    documents = splits(train=coco("a.jpg", "0" * 64, 999))
    errors = audit_manifest_against_coco(manifest, documents)
    assert any("SHA-256 mismatch" in error for error in errors)
    assert any("file size mismatch" in error for error in errors)


def test_read_manifest_validates_required_fields_and_hash(tmp_path):
    path = tmp_path / "manifest.csv"
    path.write_text("split,file_name,size_bytes,sha256\ntrain,a.jpg,3," + "a" * 64 + "\n", encoding="utf-8")
    rows, errors = read_manifest(path)
    assert errors == []
    assert rows[0]["file_name"] == "a.jpg"

    path.write_text("split,file_name,size_bytes,sha256\ntrain,../a.jpg,3,bad\n", encoding="utf-8")
    rows, errors = read_manifest(path)
    assert rows == []
    assert any("path traversal" in error for error in errors)


def test_enrich_coco_adds_manifest_hash_and_size_without_mutating_source():
    content = b"image-bytes"
    source = coco("a.jpg")
    enriched, errors = enrich_coco_document(source, [row("train", "a.jpg", content)], "train")
    assert errors == []
    assert enriched is not None
    assert enriched["images"][0]["sha256"] == hashlib.sha256(content).hexdigest()
    assert enriched["images"][0]["file_size_bytes"] == len(content)
    assert "sha256" not in source["images"][0]


def test_enrich_coco_fails_when_manifest_entry_is_missing():
    enriched, errors = enrich_coco_document(coco("missing.jpg"), [], "train")
    assert enriched is None
    assert any("missing from manifest" in error for error in errors)


import pytest

@pytest.mark.parametrize("file_name", [
    "../outside.jpg",
    "..\\outside.jpg",
    "C:/outside.jpg",
    "C:\\outside.jpg",
    "//server/share/image.jpg",
    "folder/image.jpg:stream",
])
def test_read_manifest_rejects_non_portable_paths(tmp_path, file_name):
    path = tmp_path / "manifest.csv"
    path.write_text(
        "split,file_name,size_bytes,sha256\n"
        f"train,{file_name},3,{'a' * 64}\n",
        encoding="utf-8",
    )
    rows, errors = read_manifest(path)
    assert rows == []
    assert any("safe portable relative path" in error for error in errors)
