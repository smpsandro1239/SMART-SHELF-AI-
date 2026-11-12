from pathlib import Path

import pytest

from app.coco_review import build_review_html


def document():
    return {
        "images": [
            {"id": 1, "file_name": "aisle/photo one.jpg", "width": 100, "height": 80},
            {"id": 2, "file_name": "empty.jpg", "width": 50, "height": 40},
        ],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 0, "bbox": [10, 12, 20, 30]},
            {"id": 2, "image_id": 1, "category_id": 1, "bbox": [40, 10, 15, 20]},
        ],
        "categories": [
            {"id": 0, "name": "product"},
            {"id": 1, "name": "price_label"},
        ],
    }


def make_images(root: Path):
    (root / "aisle").mkdir(parents=True)
    (root / "aisle" / "photo one.jpg").write_bytes(b"test image")
    (root / "empty.jpg").write_bytes(b"test image")


def test_review_html_renders_image_references_and_boxes(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    make_images(root)

    page, summary = build_review_html(document(), root, report_dir=tmp_path / "review")

    assert summary == {"images": 1, "annotations": 2}
    assert "aisle/photo%20one.jpg" in page
    assert '<rect x="10" y="12" width="20" height="30"' in page
    assert "product" in page
    assert "price_label" in page


def test_review_can_filter_class_and_include_unannotated_images(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    make_images(root)

    page, summary = build_review_html(
        document(), root, class_ids={1}, include_unannotated=True,
        report_dir=tmp_path / "review",
    )

    assert summary == {"images": 2, "annotations": 1}
    assert "price_label" in page
    assert "product" not in page
    assert "empty.jpg" in page


def test_review_limit_is_deterministic(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    make_images(root)

    _, summary = build_review_html(
        document(), root, include_unannotated=True, limit=1,
        report_dir=tmp_path / "review",
    )

    assert summary == {"images": 1, "annotations": 2}


def test_review_rejects_path_traversal_and_missing_files(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    make_images(root)
    invalid = document()
    invalid["images"][0]["file_name"] = "../../outside.jpg"

    with pytest.raises(ValueError, match="escapes image root"):
        build_review_html(invalid, root, report_dir=tmp_path / "review")

    windows_path = document()
    windows_path["images"][0]["file_name"] = r"..\\outside.jpg"
    with pytest.raises(ValueError, match="non-portable image path"):
        build_review_html(windows_path, root, report_dir=tmp_path / "review")

    missing = document()
    missing["images"][0]["file_name"] = "missing.jpg"
    with pytest.raises(ValueError, match="file is missing"):
        build_review_html(missing, root, report_dir=tmp_path / "review")


def test_review_escapes_untrusted_category_and_filename_text(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    (root / "unsafe.jpg").write_bytes(b"test")
    unsafe = {
        "images": [{"id": 1, "file_name": "unsafe.jpg", "width": 10, "height": 10}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 0, "bbox": [1, 1, 2, 2]}],
        "categories": [{"id": 0, "name": "<script>alert(1)</script>"}],
    }

    page, _ = build_review_html(unsafe, root, report_dir=tmp_path / "review")

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_review_rejects_invalid_coco_document(tmp_path):
    with pytest.raises(ValueError, match="invalid COCO document"):
        build_review_html({}, tmp_path)
