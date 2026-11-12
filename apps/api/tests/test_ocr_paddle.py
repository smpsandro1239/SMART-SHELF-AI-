from pathlib import Path

import pytest
from PIL import Image

from app.ocr_paddle import PaddleOCRProvider


class FakeEngine:
    def __init__(self, results):
        self.results = results
        self.received = None

    def predict(self, *, input):
        self.received = input
        return self.results


def test_paddle_adapter_maps_text_scores_and_polygons_to_normalized_regions(tmp_path):
    image_path = tmp_path / "shelf.jpg"
    Image.new("RGB", (200, 100), "white").save(image_path)
    engine = FakeEngine([{
        "rec_texts": ["COLA ZERO 1.5 L", " "],
        "rec_scores": [0.94, 0.8],
        "dt_polys": [
            [[20, 10], [120, 10], [120, 30], [20, 30]],
            [[0, 0], [10, 0], [10, 10], [0, 10]],
        ],
    }])

    regions = PaddleOCRProvider(engine).recognize(image_path)

    assert len(regions) == 1
    assert regions[0].text.text == "COLA ZERO 1.5 L"
    assert regions[0].text.confidence == pytest.approx(0.94)
    assert (regions[0].x_min, regions[0].y_min) == pytest.approx((0.1, 0.1))
    assert (regions[0].x_max, regions[0].y_max) == pytest.approx((0.6, 0.3))
    assert engine.received == str(image_path)


def test_adapter_accepts_paddle_json_result_wrapper(tmp_path):
    image_path = tmp_path / "shelf.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)

    class Result:
        json = {"res": {
            "rec_texts": ["LEITE"],
            "rec_scores": [0.88],
            "dt_polys": [[[10, 20], [50, 20], [50, 40], [10, 40]]],
        }}

    regions = PaddleOCRProvider(FakeEngine([Result()])).recognize(image_path)

    assert regions[0].text.text == "LEITE"
    assert regions[0].x_max == pytest.approx(0.5)


def test_adapter_rejects_inconsistent_result_arrays(tmp_path):
    image_path = tmp_path / "shelf.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    engine = FakeEngine([{
        "rec_texts": ["A", "B"],
        "rec_scores": [0.9],
        "dt_polys": [[[1, 1], [20, 1], [20, 20], [1, 20]]],
    }])

    with pytest.raises(ValueError, match="inconsistent"):
        PaddleOCRProvider(engine).recognize(image_path)


def test_adapter_rejects_missing_image(tmp_path):
    with pytest.raises(FileNotFoundError):
        PaddleOCRProvider(FakeEngine([])).recognize(tmp_path / "missing.jpg")


def test_adapter_rejects_invalid_polygon(tmp_path):
    image_path = tmp_path / "shelf.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    engine = FakeEngine([{
        "rec_texts": ["TEXT"],
        "rec_scores": [0.9],
        "dt_polys": [[[10, 10], [10, 10], [10, 10], [10, 10]]],
    }])

    with pytest.raises(ValueError, match="no visible area"):
        PaddleOCRProvider(engine).recognize(image_path)
