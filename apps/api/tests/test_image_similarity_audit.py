from PIL import Image, ImageDraw

from app.image_similarity_audit import audit_visual_duplicates, difference_hash, hamming_distance


def make_image(path, *, shift=0, invert=False):
    image = Image.new("RGB", (96, 64), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((16 + shift, 12, 54 + shift, 48), fill="black" if not invert else "white")
    draw.ellipse((64, 8, 84, 28), fill="black" if not invert else "white")
    image.save(path)


def test_dhash_is_stable_and_hamming_distance_is_correct(tmp_path):
    path = tmp_path / "sample.png"
    make_image(path)
    assert difference_hash(path) == difference_hash(path)
    assert hamming_distance(0b1010, 0b1001) == 2


def test_visual_audit_detects_near_duplicate_across_splits(tmp_path):
    roots = {name: tmp_path / name for name in ("train", "val", "test")}
    for root in roots.values():
        root.mkdir()
    make_image(roots["train"] / "original.png")
    make_image(roots["val"] / "slightly-different.png", shift=1)

    errors, report = audit_visual_duplicates(roots, max_distance=8)

    assert report["images_scanned"] == 2
    assert report["cross_split_matches"]
    assert any("cross dataset splits" in error for error in errors)


def test_visual_audit_allows_similar_images_inside_same_split(tmp_path):
    roots = {name: tmp_path / name for name in ("train", "val", "test")}
    for root in roots.values():
        root.mkdir()
    make_image(roots["train"] / "one.png")
    make_image(roots["train"] / "two.png", shift=1)

    errors, report = audit_visual_duplicates(roots, max_distance=8)

    assert errors == []
    assert report["within_split_matches"]
    assert report["cross_split_matches"] == []


def test_visual_audit_rejects_invalid_threshold(tmp_path):
    roots = {name: tmp_path / name for name in ("train", "val", "test")}
    for root in roots.values():
        root.mkdir()
    errors, report = audit_visual_duplicates(roots, max_distance=65)
    assert errors == ["max_distance must be an integer between 0 and 64"]
    assert report["images_scanned"] == 0


def test_visual_audit_reports_unreadable_image(tmp_path):
    roots = {name: tmp_path / name for name in ("train", "val", "test")}
    for root in roots.values():
        root.mkdir()
    (roots["train"] / "broken.jpg").write_bytes(b"not-an-image")
    errors, report = audit_visual_duplicates(roots)
    assert any("cannot decode image" in error for error in errors)
    assert len(report["unreadable_images"]) == 1
