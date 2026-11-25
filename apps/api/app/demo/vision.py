"""Deterministic shelf-vision provider for local demonstrations only.

This provider is deliberately not a trained computer-vision model. It emits one
synthetic empty-facing detection whose geometry is stable for a given image
SHA-256. It exists to exercise the existing worker and persistence contract.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.vision import DetectionResult, VisionAnalysis


class MockShelfVisionProvider:
    """Return deterministic demonstration detections for a stored image."""

    MODEL_VERSION = "mock-shelf-vision-v1"
    ALLOWED_LABELS = {"empty_facing", "low_stock", "wrong_product", "product_not_found"}

    def __init__(self, label: str | None = None) -> None:
        requested = (label or os.getenv("MOCK_VISION_DETECTION_LABEL", "empty_facing")).strip().lower()
        if requested not in self.ALLOWED_LABELS:
            raise ValueError(f"Unsupported mock detection label: {requested}")
        self.label = requested

    def analyze(self, image_path: Path) -> VisionAnalysis:
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError("Mock vision input image does not exist")
        digest = hashlib.sha256(path.read_bytes()).digest()
        # Stable, bounded geometry; no random state and no external model/runtime.
        x_min = 0.12 + (digest[0] / 255.0) * 0.08
        y_min = 0.20 + (digest[1] / 255.0) * 0.08
        width = 0.28 + (digest[2] / 255.0) * 0.08
        height = 0.34 + (digest[3] / 255.0) * 0.08
        x_max = min(0.96, x_min + width)
        y_max = min(0.96, y_min + height)
        confidence = 0.90 + (digest[4] / 255.0) * 0.09
        return VisionAnalysis(
            model_version=self.MODEL_VERSION,
            detections=[DetectionResult(
                label=self.label,
                confidence=round(confidence, 4),
                x_min=round(x_min, 4),
                y_min=round(y_min, 4),
                x_max=round(x_max, 4),
                y_max=round(y_max, 4),
            )],
        )


def create_provider() -> MockShelfVisionProvider:
    """Factory used by VISION_PROVIDER_FACTORY in Docker Compose."""
    return MockShelfVisionProvider()
