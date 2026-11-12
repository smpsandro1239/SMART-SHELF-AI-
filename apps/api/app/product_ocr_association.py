"""Associate OCR text regions with individual visual product detections.

Coordinates are normalized to the original shelf image. Each OCR region is
assigned to at most one detection, based on the fraction of its area covered
by that detection. This module does not identify SKUs or update inventory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from app.ocr_paddle import OCRRegion
from app.product_text import OCRText


@dataclass(frozen=True)
class DetectionOCR:
    detection_index: int
    texts: tuple[OCRText, ...]

    @property
    def combined_text(self) -> OCRText | None:
        """Join lines in reading order, retaining the weakest line confidence."""
        if not self.texts:
            return None
        ordered = sorted(self.texts, key=lambda item: (item.y_min, item.x_min))
        joined = " ".join(item.text.text.strip() for item in ordered)
        return OCRText(joined, min(item.text.confidence for item in ordered))


def _area(box: Sequence[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _coverage(region: OCRRegion, detection) -> float:
    x1 = max(region.x_min, detection.x_min)
    y1 = max(region.y_min, detection.y_min)
    x2 = min(region.x_max, detection.x_max)
    y2 = min(region.y_max, detection.y_max)
    intersection = _area((x1, y1, x2, y2))
    region_area = _area((region.x_min, region.y_min, region.x_max, region.y_max))
    return intersection / region_area if region_area else 0.0


def associate_ocr_regions(
    detections: Sequence,
    regions: Iterable[OCRRegion],
    *,
    minimum_region_coverage: float = 0.5,
) -> tuple[DetectionOCR, ...]:
    """Assign each text region to the best-covering product detection.

    Regions with insufficient overlap remain unassigned. Ties are resolved by
    the smaller detection box, which is a conservative choice for nested boxes.
    """
    if not 0 < minimum_region_coverage <= 1:
        raise ValueError("minimum_region_coverage must be greater than 0 and at most 1")

    assignments: list[list[OCRRegion]] = [[] for _ in detections]
    for region in regions:
        candidates: list[tuple[float, float, int]] = []
        for index, detection in enumerate(detections):
            coverage = _coverage(region, detection)
            if coverage >= minimum_region_coverage:
                detection_area = _area((
                    detection.x_min, detection.y_min,
                    detection.x_max, detection.y_max,
                ))
                candidates.append((coverage, -detection_area, index))
        if candidates:
            # Highest text-region coverage wins; smaller product box breaks ties.
            _, _, selected_index = max(candidates)
            assignments[selected_index].append(region)

    return tuple(
        DetectionOCR(
            detection_index=index,
            texts=tuple(
                region.text
                for region in sorted(items, key=lambda item: (item.y_min, item.x_min))
            ),
        )
        for index, items in enumerate(assignments)
    )
