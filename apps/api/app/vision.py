"""Provider-neutral contracts for shelf-image inference."""
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class DetectionResult(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0, le=1)
    x_min: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    x_max: float = Field(gt=0, le=1)
    y_max: float = Field(gt=0, le=1)
    product_id: int | None = Field(default=None, gt=0)

    def validate_box(self):
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError("Detection bounding box must have positive width and height")
        return self


class VisionAnalysis(BaseModel):
    model_version: str = Field(min_length=1, max_length=100)
    detections: list[DetectionResult] = Field(default_factory=list)


class VisionProvider(Protocol):
    def analyze(self, image_path: Path) -> VisionAnalysis:
        """Run inference and return validated detections for one image."""


class VisionProviderNotConfigured(RuntimeError):
    pass
