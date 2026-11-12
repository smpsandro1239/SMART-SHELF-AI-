from types import SimpleNamespace

import pytest

from app.ocr_paddle import OCRRegion
from app.product_text import OCRText
from app.product_ocr_association import associate_ocr_regions


def detection(x1, y1, x2, y2):
    return SimpleNamespace(x_min=x1, y_min=y1, x_max=x2, y_max=y2)


def region(text, confidence, x1, y1, x2, y2):
    return OCRRegion(OCRText(text, confidence), x1, y1, x2, y2)


def test_regions_are_assigned_to_the_product_box_that_contains_them():
    detections = [
        detection(0.0, 0.0, 0.45, 1.0),
        detection(0.55, 0.0, 1.0, 1.0),
    ]
    regions = [
        region("SUMO", 0.91, 0.08, 0.2, 0.30, 0.3),
        region("LARANJA", 0.87, 0.66, 0.2, 0.92, 0.3),
    ]

    result = associate_ocr_regions(detections, regions)

    assert [item.text.text for item in result[0].texts] == ["SUMO"]
    assert [item.text.text for item in result[1].texts] == ["LARANJA"]


def test_region_with_too_little_overlap_is_left_unassigned():
    detections = [detection(0.0, 0.0, 0.4, 0.4)]
    regions = [region("TEXT", 0.9, 0.35, 0.35, 0.65, 0.65)]

    result = associate_ocr_regions(detections, regions, minimum_region_coverage=0.5)

    assert result[0].texts == ()


def test_text_region_is_assigned_only_once_to_best_detection():
    detections = [
        detection(0.0, 0.0, 0.8, 0.8),
        detection(0.2, 0.2, 0.6, 0.6),
    ]
    regions = [region("SKU 123", 0.93, 0.3, 0.3, 0.5, 0.4)]

    result = associate_ocr_regions(detections, regions)

    assert result[0].texts == ()
    assert len(result[1].texts) == 1


def test_combined_text_uses_reading_order_and_lowest_confidence():
    detections = [detection(0.0, 0.0, 1.0, 1.0)]
    regions = [
        region("500 ML", 0.92, 0.2, 0.4, 0.7, 0.5),
        region("MARCA", 0.96, 0.2, 0.2, 0.7, 0.3),
    ]

    result = associate_ocr_regions(detections, regions)
    combined = result[0].combined_text

    assert combined.text == "MARCA 500 ML"
    assert combined.confidence == pytest.approx(0.92)


def test_invalid_coverage_threshold_is_rejected():
    with pytest.raises(ValueError):
        associate_ocr_regions([], [], minimum_region_coverage=0)
