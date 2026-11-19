from types import SimpleNamespace

import numpy as np
import pytest

from app.vision_onnx import (
    ONNXConfigurationError,
    ONNXShelfVisionProvider,
    PREPROCESSING_VERSION,
    _canonical_sha256,
    _fingerprinted_version,
    _sha256_file,
)


def provider_without_runtime():
    provider = object.__new__(ONNXShelfVisionProvider)
    provider._np = np
    provider.input_size = 640
    provider.confidence_threshold = 0.25
    provider.max_detections = 20
    provider.class_labels = {0: "product", 1: "empty_facing"}
    provider.sku_match_labels = {"product"}
    provider.embedding_model_version = "embed-v1"
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



def test_model_sha256_is_streamed_and_changes_with_file_content(tmp_path):
    model = tmp_path / "detector.onnx"
    model.write_bytes(b"model-a")
    first = _sha256_file(model)
    model.write_bytes(b"model-b")
    second = _sha256_file(model)

    assert len(first) == 64
    assert first != second


def test_effective_model_version_fingerprint_is_stable_and_content_sensitive():
    payload = {
        "detector_sha256": "a" * 64,
        "class_labels_sha256": "b" * 64,
        "input_size": 640,
        "confidence_threshold": 0.25,
        "max_detections": 300,
        "preprocessing_version": PREPROCESSING_VERSION,
    }
    first = _fingerprinted_version("shelf-model-v1", _canonical_sha256(payload))
    second = _fingerprinted_version("shelf-model-v1", _canonical_sha256(payload))
    changed = _fingerprinted_version(
        "shelf-model-v1",
        _canonical_sha256({**payload, "confidence_threshold": 0.30}),
    )

    assert first == second
    assert first != changed
    assert len(first) <= 100
    assert first.startswith("shelf-model-v1@")


def test_effective_model_version_rejects_invalid_fingerprint():
    with pytest.raises(ONNXConfigurationError, match="SHA-256"):
        _fingerprinted_version("model-v1", "not-a-digest")


def test_provider_rejects_symbolic_link_model_path(tmp_path):
    model = tmp_path / "detector.onnx"
    model.write_bytes(b"model")
    link = tmp_path / "detector-link.onnx"
    link.symlink_to(model)

    with pytest.raises(ONNXConfigurationError, match="symbolic links"):
        ONNXShelfVisionProvider(link, class_labels={0: "product"})



def test_provider_effective_version_binds_weights_labels_and_preprocessing(tmp_path, monkeypatch):
    import sys

    detector = tmp_path / "detector.onnx"
    detector.write_bytes(b"detector-v1")
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(InferenceSession=lambda *args, **kwargs: fake_session()),
    )

    first = ONNXShelfVisionProvider(detector, model_version="catalog-detector", class_labels={0: "product"})
    same = ONNXShelfVisionProvider(detector, model_version="catalog-detector", class_labels={0: "product"})
    relabelled = ONNXShelfVisionProvider(detector, model_version="catalog-detector", class_labels={0: "carton"})

    assert first.model_version == same.model_version
    assert first.model_version != relabelled.model_version
    assert first.model_version.endswith(_canonical_sha256({
        "detector_sha256": first.detector_sha256,
        "class_labels_sha256": first.class_labels_sha256,
        "input_size": 640,
        "confidence_threshold": 0.25,
        "max_detections": 300,
        "preprocessing_version": PREPROCESSING_VERSION,
    }))


def test_embedding_version_is_bound_to_embedding_weights(tmp_path, monkeypatch):
    import sys

    detector = tmp_path / "detector.onnx"
    embedder = tmp_path / "embedder.onnx"
    detector.write_bytes(b"detector")
    embedder.write_bytes(b"embedder-v1")
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(InferenceSession=lambda *args, **kwargs: fake_session(output_shape=(1, 256))),
    )

    first = ONNXShelfVisionProvider(
        detector, embedder, model_version="detector-v1",
        embedding_model_version="embed-v1", class_labels={0: "product"},
    )
    embedder.write_bytes(b"embedder-v2")
    second = ONNXShelfVisionProvider(
        detector, embedder, model_version="detector-v1",
        embedding_model_version="embed-v1", class_labels={0: "product"},
    )

    assert first.model_version == second.model_version
    assert first.embedding_model_version != second.embedding_model_version
    assert first.embedding_model_version.startswith("embed-v1@")



def test_provider_rejects_detector_replaced_during_session_load(tmp_path, monkeypatch):
    import sys

    detector = tmp_path / "detector.onnx"
    detector.write_bytes(b"original")
    calls = 0

    def load_session(*args, **kwargs):
        nonlocal calls
        calls += 1
        detector.write_bytes(b"replaced-during-load")
        return fake_session()

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=load_session))

    with pytest.raises(ONNXConfigurationError, match="changed while loading"):
        ONNXShelfVisionProvider(detector, class_labels={0: "product"})



def test_provider_rejects_sku_match_labels_not_present_in_class_map(tmp_path):
    model = tmp_path / "detector.onnx"
    model.write_bytes(b"not-a-real-model")

    with pytest.raises(ONNXConfigurationError, match="subset"):
        ONNXShelfVisionProvider(
            model,
            class_labels={0: "product"},
            sku_match_labels={"product", "empty_facing"},
        )


def test_non_product_detection_does_not_generate_sku_embedding(tmp_path):
    from PIL import Image

    image_path = tmp_path / "shelf.png"
    Image.new("RGB", (640, 640), "white").save(image_path)
    provider = provider_without_runtime()
    provider._image = Image
    provider._detector_input = "images"
    provider._detector_output = "detections"
    provider._embedder = object()
    provider._detector = SimpleNamespace(
        run=lambda outputs, inputs: [np.array([[0.1, 0.1, 0.5, 0.5, 0.95, 1]], dtype=np.float32)]
    )
    embedding_calls = []
    provider._embedding = lambda image, box: embedding_calls.append(box) or [1.0, 0.0]
    provider.model_version = "test-model"

    result = provider.analyze(image_path)

    assert result.detections[0].label == "empty_facing"
    assert result.detections[0].embedding is None
    assert embedding_calls == []


def test_product_detection_can_generate_sku_embedding(tmp_path):
    from PIL import Image

    image_path = tmp_path / "shelf.png"
    Image.new("RGB", (640, 640), "white").save(image_path)
    provider = provider_without_runtime()
    provider._image = Image
    provider._detector_input = "images"
    provider._detector_output = "detections"
    provider._embedder = object()
    provider._detector = SimpleNamespace(
        run=lambda outputs, inputs: [np.array([[0.1, 0.1, 0.5, 0.5, 0.95, 0]], dtype=np.float32)]
    )
    embedding_calls = []
    provider._embedding = lambda image, box: embedding_calls.append(box) or [1.0, 0.0]
    provider.model_version = "test-model"

    result = provider.analyze(image_path)

    assert result.detections[0].label == "product"
    assert result.detections[0].embedding == [1.0, 0.0]
    assert result.detections[0].embedding_model_version == "embed-v1"
    assert len(embedding_calls) == 1
