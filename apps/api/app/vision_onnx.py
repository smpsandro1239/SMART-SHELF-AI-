"""CPU-first ONNX provider for shelf object detection and SKU embeddings.

Model contracts are deliberately narrow and documented:
- Detector input: float32 [1, 3, H, W], RGB, range [0, 1].
- Detector output: [N, 6] or [1, N, 6], rows are normalized
  x1,y1,x2,y2,confidence,class_id after model-side NMS.
- Embedder input: same image tensor contract, output: one finite vector.
The detector must export post-NMS boxes. Raw YOLO head tensors are not accepted.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from app.vision import DetectionResult, VisionAnalysis


class ONNXConfigurationError(RuntimeError):
    pass


def _env_int(name: str, default: int, minimum: int = 1, maximum: int = 4096) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ONNXConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ONNXConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


def _env_float(name: str, default: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ONNXConfigurationError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ONNXConfigurationError(f"{name} must be between {minimum} and {maximum}")
    return value


PREPROCESSING_VERSION = "rgb-letterbox-bilinear-114-v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ONNXConfigurationError(f"Cannot read model file for SHA-256: {path.name}") from exc
    return digest.hexdigest()


def _fingerprinted_version(configured_version: str, fingerprint: str) -> str:
    base = configured_version.strip()
    if not base:
        raise ONNXConfigurationError("Model version cannot be empty")
    if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
        raise ONNXConfigurationError("Model fingerprint must be a SHA-256 hex digest")
    # ShelfImageDetection.model_version is limited to 100 characters.
    return f"{base[:32]}@{fingerprint}"


def _canonical_sha256(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ONNXShelfVisionProvider:
    """Run an exported detector and optional image embedder with ONNX Runtime."""

    def __init__(
        self,
        detector_path: str | Path,
        embedding_path: str | Path | None = None,
        *,
        model_version: str = "shelf-onnx-v1",
        embedding_model_version: str = "shelf-embedding-v1",
        input_size: int = 640,
        confidence_threshold: float = 0.25,
        max_detections: int = 300,
        providers: list[str] | None = None,
        class_labels: dict[int, str] | None = None,
    ):
        self.detector_path = Path(detector_path)
        self.embedding_path = Path(embedding_path) if embedding_path else None
        self.configured_model_version = model_version.strip()
        self.configured_embedding_model_version = embedding_model_version.strip()
        self.input_size = input_size
        self.confidence_threshold = confidence_threshold
        self.max_detections = max_detections
        if not self.detector_path.is_file():
            raise ONNXConfigurationError("VISION_DETECTOR_MODEL_PATH does not point to a file")
        if self.embedding_path and not self.embedding_path.is_file():
            raise ONNXConfigurationError("VISION_EMBEDDING_MODEL_PATH does not point to a file")
        if not isinstance(class_labels, dict) or not class_labels:
            raise ONNXConfigurationError("VISION_CLASS_LABELS_JSON must define at least one class")
        normalized_labels = {}
        for class_id, label in class_labels.items():
            if isinstance(class_id, bool) or not isinstance(class_id, int) or class_id < 0:
                raise ONNXConfigurationError("Class IDs must be non-negative integers")
            if not isinstance(label, str) or not label.strip() or len(label.strip()) > 120:
                raise ONNXConfigurationError("Class labels must be non-empty strings of at most 120 characters")
            normalized_labels[class_id] = label.strip()
        self.class_labels = normalized_labels
        self.class_labels_sha256 = _canonical_sha256({
            str(class_id): label for class_id, label in sorted(normalized_labels.items())
        })
        if self.detector_path.is_symlink() or (self.embedding_path and self.embedding_path.is_symlink()):
            raise ONNXConfigurationError("Model paths must not be symbolic links")
        self.detector_sha256 = _sha256_file(self.detector_path)
        self.embedding_sha256 = _sha256_file(self.embedding_path) if self.embedding_path else None
        detector_fingerprint = _canonical_sha256({
            "detector_sha256": self.detector_sha256,
            "class_labels_sha256": self.class_labels_sha256,
            "input_size": self.input_size,
            "confidence_threshold": self.confidence_threshold,
            "max_detections": self.max_detections,
            "preprocessing_version": PREPROCESSING_VERSION,
        })
        self.model_version = _fingerprinted_version(self.configured_model_version, detector_fingerprint)
        if self.embedding_sha256:
            embedding_fingerprint = _canonical_sha256({
                "embedding_sha256": self.embedding_sha256,
                "input_size": self.input_size,
                "preprocessing_version": PREPROCESSING_VERSION,
            })
            self.embedding_model_version = _fingerprinted_version(
                self.configured_embedding_model_version, embedding_fingerprint
            )
        else:
            self.embedding_model_version = None
        self.preprocessing_version = PREPROCESSING_VERSION
        try:
            import onnxruntime as ort
            import numpy as np
            from PIL import Image
        except ImportError as exc:
            raise ONNXConfigurationError(
                "Install onnxruntime, numpy and Pillow to use the ONNX vision provider"
            ) from exc

        self._np = np
        self._image = Image
        selected_providers = providers or ["CPUExecutionProvider"]
        self._detector = ort.InferenceSession(str(self.detector_path), providers=selected_providers)
        if self.detector_path.is_symlink() or _sha256_file(self.detector_path) != self.detector_sha256:
            raise ONNXConfigurationError("Detector model changed while loading")
        self._detector_input = self._single_input_name(self._detector, "detector")
        self._detector_output = self._single_output_name(self._detector, "detector")
        self._validate_detector_contract(self._detector, self.input_size)
        if self.embedding_path:
            self._embedder = ort.InferenceSession(str(self.embedding_path), providers=selected_providers)
            if self.embedding_path.is_symlink() or _sha256_file(self.embedding_path) != self.embedding_sha256:
                raise ONNXConfigurationError("Embedding model changed while loading")
            self._embedding_input = self._single_input_name(self._embedder, "embedding")
            self._embedding_output = self._single_output_name(self._embedder, "embedding")
            self._validate_embedding_contract(self._embedder, self.input_size)
        else:
            self._embedder = None
            self._embedding_input = None
            self._embedding_output = None

    @staticmethod
    def _single_input_name(session, label: str) -> str:
        inputs = session.get_inputs()
        if len(inputs) != 1:
            raise ONNXConfigurationError(f"{label} model must expose exactly one input")
        return inputs[0].name

    @staticmethod
    def _single_output_name(session, label: str) -> str:
        outputs = session.get_outputs()
        if len(outputs) != 1:
            raise ONNXConfigurationError(f"{label} model must expose exactly one output")
        return outputs[0].name

    @staticmethod
    def _validate_detector_contract(session, input_size: int) -> None:
        input_meta = session.get_inputs()[0]
        output_meta = session.get_outputs()[0]
        if input_meta.type != "tensor(float)" or output_meta.type != "tensor(float)":
            raise ONNXConfigurationError("Detector input and output must use float32 tensors")
        input_shape = input_meta.shape
        output_shape = output_meta.shape
        if not isinstance(input_shape, (list, tuple)) or len(input_shape) != 4:
            raise ONNXConfigurationError("Detector input must have NCHW rank 4")
        if input_shape[1] != 3:
            raise ONNXConfigurationError("Detector input must have exactly 3 RGB channels")
        for dimension in input_shape[2:]:
            if isinstance(dimension, int) and dimension != input_size:
                raise ONNXConfigurationError("Detector input height and width must match VISION_INPUT_SIZE")
        if isinstance(input_shape[0], int) and input_shape[0] != 1:
            raise ONNXConfigurationError("Detector input batch size must be 1 or dynamic")
        if not isinstance(output_shape, (list, tuple)) or len(output_shape) not in (2, 3):
            raise ONNXConfigurationError("Detector output must have rank 2 or 3")
        if output_shape[-1] != 6:
            raise ONNXConfigurationError("Detector output must expose exactly 6 values per detection")

    @staticmethod
    def _validate_embedding_contract(session, input_size: int) -> None:
        input_meta = session.get_inputs()[0]
        output_meta = session.get_outputs()[0]
        if input_meta.type != "tensor(float)" or output_meta.type != "tensor(float)":
            raise ONNXConfigurationError("Embedding input and output must use float32 tensors")
        input_shape = input_meta.shape
        output_shape = output_meta.shape
        if not isinstance(input_shape, (list, tuple)) or len(input_shape) != 4:
            raise ONNXConfigurationError("Embedding input must have NCHW rank 4")
        if input_shape[1] != 3:
            raise ONNXConfigurationError("Embedding input must have exactly 3 RGB channels")
        for dimension in input_shape[2:]:
            if isinstance(dimension, int) and dimension != input_size:
                raise ONNXConfigurationError("Embedding input height and width must match VISION_INPUT_SIZE")
        if isinstance(input_shape[0], int) and input_shape[0] != 1:
            raise ONNXConfigurationError("Embedding input batch size must be 1 or dynamic")
        if not isinstance(output_shape, (list, tuple)) or not output_shape:
            raise ONNXConfigurationError("Embedding output must be a non-empty tensor")

    def _preprocess(self, image):
        np = self._np
        width, height = image.size
        target = self.input_size
        scale = min(target / width, target / height)
        resized_width = max(1, round(width * scale))
        resized_height = max(1, round(height * scale))
        resized = image.resize((resized_width, resized_height), self._image.Resampling.BILINEAR)
        canvas = self._image.new("RGB", (target, target), (114, 114, 114))
        pad_x = (target - resized_width) // 2
        pad_y = (target - resized_height) // 2
        canvas.paste(resized, (pad_x, pad_y))
        tensor = np.asarray(canvas, dtype=np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
        return tensor, (width, height, scale, pad_x, pad_y)

    def _decode(self, raw, original_size, transform):
        np = self._np
        values = np.asarray(raw)
        if values.ndim == 3 and values.shape[0] == 1:
            values = values[0]
        if values.ndim != 2 or values.shape[1] != 6:
            raise ValueError("Detector output must have shape [N, 6] or [1, N, 6]")
        width, height = original_size
        _, _, scale, pad_x, pad_y = transform
        detections = []
        for row in values:
            x1, y1, x2, y2, score, raw_class_id = map(float, row)
            if not all(np.isfinite(v) for v in (x1, y1, x2, y2, score, raw_class_id)):
                raise ValueError("Detector output contains non-finite values")
            if raw_class_id < 0 or not raw_class_id.is_integer():
                raise ValueError("Detector class_id must be a non-negative integer")
            if not 0 <= score <= 1:
                raise ValueError("Detector confidence must be between 0 and 1")
            if score < self.confidence_threshold:
                continue
            if not all(0 <= coordinate <= 1 for coordinate in (x1, y1, x2, y2)):
                raise ValueError("Detector coordinates must be normalized to [0, 1]")
            class_id = int(raw_class_id)
            # Coordinates are normalized against the square model input.
            x1 = (x1 * self.input_size - pad_x) / scale
            x2 = (x2 * self.input_size - pad_x) / scale
            y1 = (y1 * self.input_size - pad_y) / scale
            y2 = (y2 * self.input_size - pad_y) / scale
            x1, x2 = max(0.0, min(width, x1)), max(0.0, min(width, x2))
            y1, y2 = max(0.0, min(height, y1)), max(0.0, min(height, y2))
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append((score, class_id, x1 / width, y1 / height, x2 / width, y2 / height))
        detections.sort(key=lambda item: item[0], reverse=True)
        return detections[: self.max_detections]

    def _embedding(self, image, box):
        if self._embedder is None:
            return None
        _, x1, y1, x2, y2 = box
        width, height = image.size
        left, top = max(0, int(x1 * width)), max(0, int(y1 * height))
        right, bottom = min(width, int(x2 * width + 0.999)), min(height, int(y2 * height + 0.999))
        if right <= left or bottom <= top:
            return None
        crop = image.crop((left, top, right, bottom)).resize(
            (self.input_size, self.input_size), self._image.Resampling.BILINEAR
        )
        tensor = self._np.asarray(crop, dtype=self._np.float32) / 255.0
        tensor = self._np.transpose(tensor, (2, 0, 1))[None, ...]
        output = self._embedder.run([self._embedding_output], {self._embedding_input: tensor})[0]
        vector = self._np.asarray(output, dtype=self._np.float32).reshape(-1)
        norm = float(self._np.linalg.norm(vector))
        if not self._np.isfinite(vector).all() or not self._np.isfinite(norm) or norm <= 1e-12:
            return None
        return (vector / norm).astype(self._np.float32).tolist()

    def analyze(self, image_path: Path) -> VisionAnalysis:
        with self._image.open(image_path) as source:
            image = source.convert("RGB")
        tensor, transform = self._preprocess(image)
        raw = self._detector.run(
            [self._detector_output], {self._detector_input: tensor}
        )[0]
        boxes = self._decode(raw, image.size, transform)
        detections = []
        for score, class_id, x1, y1, x2, y2 in boxes:
            label = self.class_labels.get(class_id)
            if label is None:
                raise ValueError(f"Detector returned unknown class_id: {class_id}")
            box = (score, x1, y1, x2, y2)
            embedding = self._embedding(image, box)
            detections.append(DetectionResult(
                label=label,
                confidence=score,
                x_min=x1,
                y_min=y1,
                x_max=x2,
                y_max=y2,
                embedding=embedding,
                embedding_model_version=self.embedding_model_version if embedding is not None else None,
            ))
        return VisionAnalysis(model_version=self.model_version, detections=detections)


def create_provider() -> ONNXShelfVisionProvider:
    """Factory referenced by VISION_PROVIDER_FACTORY."""
    detector = os.getenv("VISION_DETECTOR_MODEL_PATH", "").strip()
    embedder = os.getenv("VISION_EMBEDDING_MODEL_PATH", "").strip() or None
    version = os.getenv("VISION_MODEL_VERSION", "shelf-onnx-v1").strip()
    labels_raw = os.getenv("VISION_CLASS_LABELS_JSON", "").strip()
    if not labels_raw:
        raise ONNXConfigurationError("VISION_CLASS_LABELS_JSON is required for a real ONNX detector")
    try:
        labels_payload = json.loads(labels_raw)
        if not isinstance(labels_payload, dict):
            raise ValueError("class labels must be a JSON object")
        class_labels = {}
        for raw_id, label in labels_payload.items():
            if not isinstance(raw_id, str) or not raw_id.isdecimal():
                raise ValueError("class label keys must be non-negative integer strings")
            class_labels[int(raw_id)] = label
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ONNXConfigurationError("VISION_CLASS_LABELS_JSON must be a JSON object mapping class IDs to labels") from exc
    embedding_version = os.getenv("VISION_EMBEDDING_MODEL_VERSION", "shelf-embedding-v1").strip()
    if not detector:
        raise ONNXConfigurationError("VISION_DETECTOR_MODEL_PATH is required")
    if not version:
        raise ONNXConfigurationError("VISION_MODEL_VERSION cannot be empty")
    if embedder and not embedding_version:
        raise ONNXConfigurationError("VISION_EMBEDDING_MODEL_VERSION cannot be empty when an embedder is configured")
    return ONNXShelfVisionProvider(
        detector,
        embedder,
        model_version=version,
        embedding_model_version=embedding_version,
        input_size=_env_int("VISION_INPUT_SIZE", 640, 32, 4096),
        confidence_threshold=_env_float("VISION_CONFIDENCE_THRESHOLD", 0.25),
        max_detections=_env_int("VISION_MAX_DETECTIONS", 300, 1, 2000),
        class_labels=class_labels,
    )
