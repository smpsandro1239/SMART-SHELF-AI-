"""Provider-neutral contracts for shelf-image inference."""
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field, model_validator
import math


class DetectionResult(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0, le=1)
    x_min: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    x_max: float = Field(gt=0, le=1)
    y_max: float = Field(gt=0, le=1)
    product_id: int | None = Field(default=None, gt=0)
    embedding: list[float] | None = Field(default=None, min_length=1, max_length=4096)
    embedding_model_version: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_embedding(self):
        if self.embedding is None and self.embedding_model_version is not None:
            raise ValueError("embedding_model_version requires an embedding")
        if self.embedding is not None:
            if not self.embedding_model_version:
                raise ValueError("embedding requires embedding_model_version")
            if any(not math.isfinite(value) for value in self.embedding):
                raise ValueError("embedding values must be finite")
            if not any(value != 0 for value in self.embedding):
                raise ValueError("embedding cannot be a zero vector")
        return self

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
