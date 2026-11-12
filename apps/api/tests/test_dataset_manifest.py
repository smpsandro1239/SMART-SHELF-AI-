import hashlib

from app.dataset_manifest import build_manifest, sha256_file


def test_manifest_records_sorted_paths_sizes_and_hashes(tmp_path):
    train = tmp_path / "train"
    val = tmp_path / "val"
    test = tmp_path / "test"
    for root in (train, val, test):
        root.mkdir()
    (train / "z.jpg").write_bytes(b"image-z")
    (train / "a.png").write_bytes(b"image-a")
    (val / "b.webp").write_bytes(b"image-b")

    rows, errors = build_manifest({"train": train, "val": val, "test": test})

    assert errors == []
    assert [(row["split"], row["file_name"]) for row in rows] == [
        ("train", "a.png"),
        ("train", "z.jpg"),
        ("val", "b.webp"),
    ]
    assert rows[0]["size_bytes"] == len(b"image-a")
    assert rows[0]["sha256"] == hashlib.sha256(b"image-a").hexdigest()


def test_manifest_reports_missing_split_directory(tmp_path):
    rows, errors = build_manifest({"train": tmp_path / "missing"})
    assert rows == []
    assert any("not a directory" in error for error in errors)


def test_manifest_rejects_empty_image_file(tmp_path):
    root = tmp_path / "train"
    root.mkdir()
    (root / "empty.jpg").write_bytes(b"")
    rows, errors = build_manifest({"train": root})
    assert rows == []
    assert any("image file is empty" in error for error in errors)


def test_sha256_reads_file_in_chunks(tmp_path):
    path = tmp_path / "large.bin"
    content = b"x" * (1024 * 1024 + 17)
    path.write_bytes(content)
    assert sha256_file(path) == hashlib.sha256(content).hexdigest()
