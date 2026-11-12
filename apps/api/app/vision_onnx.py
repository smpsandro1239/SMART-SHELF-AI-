"""CPU-first ONNX provider for shelf object detection and SKU embeddings.

Model contracts are deliberately narrow and documented:
- Detector input: float32 [1, 3, H, W], RGB, range [0, 1].
- Detector output: [N, 6] or [1, N, 6], rows are normalized
  x1,y1,x2,y2,confidence,class_id after model-side NMS.
- Embedder input: same image tensor contract, output: one finite vector.
The detector must export post-NMS boxes. Raw YOLO head tensors are not accepted.
"""
from __future__ import annotations

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


class ONNXShelfVisionProvider:
    """Run an exported detector and optional image embedder with ONNX Runtime."""

    def __init__(
        self,
        detector_path: str | Path,
        embedding_path: str | Path | None = None,
        *,
        model_version: str = "shelf-onnx-v1",
        input_size: int = 640,
        confidence_threshold: float = 0.25,
        max_detections: int = 300,
        providers: list[str] | None = None,
    ):
        self.detector_path = Path(detector_path)
        self.embedding_path = Path(embedding_path) if embedding_path else None
        self.model_version = model_version
        self.input_size = input_size
        self.confidence_threshold = confidence_threshold
        self.max_detections = max_detections
        if not self.detector_path.is_file():
            raise ONNXConfigurationError("VISION_DETECTOR_MODEL_PATH does not point to a file")
        if self.embedding_path and not self.embedding_path.is_file():
            raise ONNXConfigurationError("VISION_EMBEDDING_MODEL_PATH does not point to a file")
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
        self._detector_input = self._single_input_name(self._detector, "detector")
        self._detector_output = self._single_output_name(self._detector, "detector")
        if self.embedding_path:
            self._embedder = ort.InferenceSession(str(self.embedding_path), providers=selected_providers)
            self._embedding_input = self._single_input_name(self._embedder, "embedding")
            self._embedding_output = self._single_output_name(self._embedder, "embedding")
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
            x1, y1, x2, y2, score, _class_id = map(float, row)
            if not all(np.isfinite(v) for v in (x1, y1, x2, y2, score)):
                continue
            if score < self.confidence_threshold:
                continue
            # Coordinates are normalized against the square model input.
            x1 = (x1 * self.input_size - pad_x) / scale
            x2 = (x2 * self.input_size - pad_x) / scale
            y1 = (y1 * self.input_size - pad_y) / scale
            y2 = (y2 * self.input_size - pad_y) / scale
            x1, x2 = max(0.0, min(width, x1)), max(0.0, min(width, x2))
            y1, y2 = max(0.0, min(height, y1)), max(0.0, min(height, y2))
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append((score, x1 / width, y1 / height, x2 / width, y2 / height))
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
        for score, x1, y1, x2, y2 in boxes:
            box = (score, x1, y1, x2, y2)
            embedding = self._embedding(image, box)
            detections.append(DetectionResult(
                label="product",
                confidence=score,
                x_min=x1,
                y_min=y1,
                x_max=x2,
                y_max=y2,
                embedding=embedding,
                embedding_model_version=self.model_version if embedding is not None else None,
            ))
        return VisionAnalysis(model_version=self.model_version, detections=detections)


def create_provider() -> ONNXShelfVisionProvider:
    """Factory referenced by VISION_PROVIDER_FACTORY."""
    detector = os.getenv("VISION_DETECTOR_MODEL_PATH", "").strip()
    embedder = os.getenv("VISION_EMBEDDING_MODEL_PATH", "").strip() or None
    version = os.getenv("VISION_MODEL_VERSION", "shelf-onnx-v1").strip()
    if not detector:
        raise ONNXConfigurationError("VISION_DETECTOR_MODEL_PATH is required")
    if not version:
        raise ONNXConfigurationError("VISION_MODEL_VERSION cannot be empty")
    return ONNXShelfVisionProvider(
        detector,
        embedder,
        model_version=version,
        input_size=_env_int("VISION_INPUT_SIZE", 640, 32, 4096),
        confidence_threshold=_env_float("VISION_CONFIDENCE_THRESHOLD", 0.25),
        max_detections=_env_int("VISION_MAX_DETECTIONS", 300, 1, 2000),
    )
