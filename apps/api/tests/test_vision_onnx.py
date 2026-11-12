import numpy as np
import pytest

from app.vision_onnx import ONNXConfigurationError, ONNXShelfVisionProvider


def provider_without_runtime():
    provider = object.__new__(ONNXShelfVisionProvider)
    provider._np = np
    provider.input_size = 640
    provider.confidence_threshold = 0.25
    provider.max_detections = 20
    return provider


def test_decode_maps_letterboxed_boxes_back_to_original_image():
    provider = provider_without_runtime()
    # Original image 640x320; letterbox adds 160px top and bottom.
    transform = (640, 320, 1.0, 0, 160)
    raw = np.array([[0.1, 0.375, 0.9, 0.625, 0.95, 0]], dtype=np.float32)

    boxes = provider._decode(raw, (640, 320), transform)

    assert len(boxes) == 1
    score, x1, y1, x2, y2 = boxes[0]
    assert score == pytest.approx(0.95)
    assert (x1, y1, x2, y2) == pytest.approx((0.1, 0.25, 0.9, 0.75))


def test_decode_discards_low_confidence_and_degenerate_boxes():
    provider = provider_without_runtime()
    transform = (640, 640, 1.0, 0, 0)
    raw = np.array([
        [0.1, 0.1, 0.5, 0.5, 0.2, 0],
        [0.4, 0.4, 0.4, 0.8, 0.9, 0],
    ], dtype=np.float32)

    assert provider._decode(raw, (640, 640), transform) == []


def test_decode_rejects_unknown_detector_output_shape():
    provider = provider_without_runtime()
    with pytest.raises(ValueError, match="shape"):
        provider._decode(np.zeros((1, 84, 8400)), (640, 640), (640, 640, 1, 0, 0))


def test_provider_requires_existing_detector_file(tmp_path):
    with pytest.raises(ONNXConfigurationError, match="does not point to a file"):
        ONNXShelfVisionProvider(tmp_path / "missing.onnx")
