"""Optional PaddleOCR 3.x adapter with normalized text-region coordinates.

Install the optional dependencies from requirements-ocr.txt. The API package
does not import PaddleOCR unless this provider is explicitly constructed.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from app.product_text import OCRText


@dataclass(frozen=True)
class OCRRegion:
    text: OCRText
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        if not (0 <= self.x_min < self.x_max <= 1):
            raise ValueError("OCR region x coordinates must be normalized and ordered")
        if not (0 <= self.y_min < self.y_max <= 1):
            raise ValueError("OCR region y coordinates must be normalized and ordered")


class PaddleOCRProvider:
    """Thin adapter around PaddleOCR's v3 predict() result contract."""

    def __init__(self, engine: Any | None = None) -> None:
        if engine is None:
            try:
                module = importlib.import_module("paddleocr")
            except ImportError as exc:
                raise RuntimeError(
                    "PaddleOCR is optional; install apps/api/requirements-ocr.txt"
                ) from exc
            engine = module.PaddleOCR(
                lang="pt",
                ocr_version="PP-OCRv5",
                device="cpu",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        if not callable(getattr(engine, "predict", None)):
            raise TypeError("PaddleOCR engine must expose predict(input=...)")
        self._engine = engine

    @staticmethod
    def _as_mapping(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return item.get("res", item)
        payload = getattr(item, "json", None)
        if callable(payload):
            payload = payload()
        if isinstance(payload, dict):
            return payload.get("res", payload)
        raise ValueError("Unsupported PaddleOCR result object; expected mapping or .json")

    @staticmethod
    def _as_sequence(value: Any) -> list[Any]:
        if value is None:
            return []
        tolist = getattr(value, "tolist", None)
        if callable(tolist):
            value = tolist()
        return list(value)

    @staticmethod
    def _points_to_box(points: Any, width: int, height: int) -> tuple[float, float, float, float]:
        # PaddleOCR returns a polygon with pixel coordinates (normally 4x2).
        coordinates = list(points)
        xs = [float(point[0]) for point in coordinates]
        ys = [float(point[1]) for point in coordinates]
        if not xs or not ys:
            raise ValueError("OCR polygon is empty")
        x1 = max(0.0, min(1.0, min(xs) / width))
        y1 = max(0.0, min(1.0, min(ys) / height))
        x2 = max(0.0, min(1.0, max(xs) / width))
        y2 = max(0.0, min(1.0, max(ys) / height))
        if x1 >= x2 or y1 >= y2:
            raise ValueError("OCR polygon has no visible area inside the image")
        return x1, y1, x2, y2

    def recognize(self, image_path: Path) -> tuple[OCRRegion, ...]:
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError("OCR input image is unavailable")
        with Image.open(path) as image:
            width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("OCR image dimensions must be positive")

        raw_results = self._engine.predict(input=str(path))
        if raw_results is None:
            return ()
        if isinstance(raw_results, (dict,)) or hasattr(raw_results, "json"):
            raw_results = [raw_results]

        regions: list[OCRRegion] = []
        for raw in raw_results:
            result = self._as_mapping(raw)
            texts = self._as_sequence(result.get("rec_texts"))
            scores = self._as_sequence(result.get("rec_scores"))
            polygon_values = result.get("dt_polys")
            if polygon_values is None:
                polygon_values = result.get("rec_polys")
            polygons = self._as_sequence(polygon_values)
            if not (len(texts) == len(scores) == len(polygons)):
                raise ValueError("PaddleOCR texts, scores and polygons have inconsistent lengths")
            for text, score, polygon in zip(texts, scores, polygons):
                if not str(text).strip():
                    continue
                box = self._points_to_box(polygon, width, height)
                regions.append(OCRRegion(
                    text=OCRText(str(text), float(score)),
                    x_min=box[0], y_min=box[1], x_max=box[2], y_max=box[3],
                ))
        return tuple(regions)


def create_provider() -> PaddleOCRProvider:
    """Factory compatible with optional provider loading conventions."""
    return PaddleOCRProvider()
