from types import SimpleNamespace

import numpy as np
import pytest

from app.vision_onnx import ONNXConfigurationError, ONNXShelfVisionProvider


def provider_without_runtime():
    provider = object.__new__(ONNXShelfVisionProvider)
    provider._np = np
    provider.input_size = 640
    provider.confidence_threshold = 0.25
    provider.max_detections = 20
    provider.class_labels = {0: "product", 1: "empty_facing"}
    return provider


def test_decode_maps_letterboxed_boxes_back_to_original_image():
    provider = provider_without_runtime()
    # Original image 640x320; letterbox adds 160px top and bottom.
    transform = (640, 320, 1.0, 0, 160)
    raw = np.array([[0.1, 0.375, 0.9, 0.625, 0.95, 0]], dtype=np.float32)

    boxes = provider._decode(raw, (640, 320), transform)

    assert len(boxes) == 1
    score, class_id, x1, y1, x2, y2 = boxes[0]
    assert class_id == 0
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



def test_decode_preserves_class_id_for_semantic_mapping():
    provider = provider_without_runtime()
    raw = np.array([[0.1, 0.1, 0.5, 0.5, 0.95, 1]], dtype=np.float32)

    boxes = provider._decode(raw, (640, 640), (640, 640, 1, 0, 0))

    assert boxes[0][1] == 1


@pytest.mark.parametrize("class_id", [-1, 1.5, np.nan])
def test_decode_rejects_invalid_class_ids(class_id):
    provider = provider_without_runtime()
    raw = np.array([[0.1, 0.1, 0.5, 0.5, 0.95, class_id]], dtype=np.float32)

    with pytest.raises(ValueError, match="class_id|non-finite"):
        provider._decode(raw, (640, 640), (640, 640, 1, 0, 0))


@pytest.mark.parametrize("confidence", [-0.01, 1.01, np.nan])
def test_decode_rejects_invalid_confidence(confidence):
    provider = provider_without_runtime()
    raw = np.array([[0.1, 0.1, 0.5, 0.5, confidence, 0]], dtype=np.float32)

    with pytest.raises(ValueError, match="confidence|non-finite"):
        provider._decode(raw, (640, 640), (640, 640, 1, 0, 0))


def test_provider_rejects_missing_or_empty_class_catalog(tmp_path):
    model = tmp_path / "detector.onnx"
    model.write_bytes(b"not-a-real-model")

    with pytest.raises(ONNXConfigurationError, match="VISION_CLASS_LABELS_JSON"):
        ONNXShelfVisionProvider(model, class_labels={})


def test_provider_rejects_invalid_class_catalog(tmp_path):
    model = tmp_path / "detector.onnx"
    model.write_bytes(b"not-a-real-model")

    with pytest.raises(ONNXConfigurationError, match="Class IDs"):
        ONNXShelfVisionProvider(model, class_labels={-1: "product"})



def fake_session(input_type="tensor(float)", output_type="tensor(float)", input_shape=(1, 3, 640, 640), output_shape=(1, "detections", 6)):
    return SimpleNamespace(
        get_inputs=lambda: [SimpleNamespace(name="images", type=input_type, shape=list(input_shape))],
        get_outputs=lambda: [SimpleNamespace(name="detections", type=output_type, shape=list(output_shape))],
    )


def test_detector_contract_accepts_documented_float32_nchw_post_nms_output():
    ONNXShelfVisionProvider._validate_detector_contract(fake_session(), 640)


@pytest.mark.parametrize(
    "session, message",
    [
        (fake_session(input_type="tensor(uint8)"), "float32"),
        (fake_session(input_shape=(1, 1, 640, 640)), "3 RGB channels"),
        (fake_session(input_shape=(1, 3, 320, 640)), "VISION_INPUT_SIZE"),
        (fake_session(output_shape=(1, 84, 8400)), "6 values"),
        (fake_session(output_shape=(1, 100, 7)), "6 values"),
    ],
)
def test_detector_contract_rejects_incompatible_model_metadata(session, message):
    with pytest.raises(ONNXConfigurationError, match=message):
        ONNXShelfVisionProvider._validate_detector_contract(session, 640)


def test_embedding_contract_requires_float32_rgb_tensor():
    session = fake_session(output_shape=(1, 256))
    ONNXShelfVisionProvider._validate_embedding_contract(session, 640)


def test_embedding_contract_rejects_wrong_input_dtype():
    session = fake_session(input_type="tensor(uint8)", output_shape=(1, 256))
    with pytest.raises(ONNXConfigurationError, match="float32"):
        ONNXShelfVisionProvider._validate_embedding_contract(session, 640)


def test_analyze_uses_configured_label_for_class_id(tmp_path):
    from PIL import Image

    image_path = tmp_path / "shelf.png"
    Image.new("RGB", (640, 640), "white").save(image_path)
    provider = provider_without_runtime()
    provider._image = Image
    provider._detector_input = "images"
    provider._detector_output = "detections"
    provider._embedder = None
    provider._detector = SimpleNamespace(
        run=lambda outputs, inputs: [np.array([[0.1, 0.1, 0.5, 0.5, 0.95, 1]], dtype=np.float32)]
    )
    provider.model_version = "test-model"
    provider.class_labels = {1: "empty_facing"}

    result = provider.analyze(image_path)

    assert len(result.detections) == 1
    assert result.detections[0].label == "empty_facing"


def test_analyze_aborts_when_model_returns_unmapped_class_id(tmp_path):
    from PIL import Image

    image_path = tmp_path / "shelf.png"
    Image.new("RGB", (640, 640), "white").save(image_path)
    provider = provider_without_runtime()
    provider._image = Image
    provider._detector_input = "images"
    provider._detector_output = "detections"
    provider._embedder = None
    provider._detector = SimpleNamespace(
        run=lambda outputs, inputs: [np.array([[0.1, 0.1, 0.5, 0.5, 0.95, 9]], dtype=np.float32)]
    )
    provider.model_version = "test-model"
    provider.class_labels = {0: "product"}

    with pytest.raises(ValueError, match="unknown class_id"):
        provider.analyze(image_path)
