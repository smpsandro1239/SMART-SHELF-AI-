"""Read-only comparison of persisted image detections with an active planogram.

The comparison is deliberately conservative: without a per-cell visibility
calibration, absence of a product is UNKNOWN rather than EMPTY. Results are
computed on demand and never mutate inventory or planogram history.
"""
from __future__ import annotations

from typing import Iterable
import hashlib
import json

from app import models
from app.shelf_layout import ShelfCell, compare_detections_to_cells


def compare_active_planogram_detections(
    planogram: models.ShelfPlanogram,
    detections: Iterable[models.ShelfImageDetection],
) -> list[dict]:
    """Return per-cell comparison data while preserving detection provenance."""
    if planogram.status != "ACTIVE":
        raise ValueError("Only an ACTIVE planogram can be compared")

    ordered_detections = tuple(detections)
    cells = [
        ShelfCell(
            cell_id=cell.cell_code,
            x_min=cell.x_min,
            y_min=cell.y_min,
            x_max=cell.x_max,
            y_max=cell.y_max,
            expected_product_id=cell.expected_product_id,
            expected_facings=cell.expected_facings,
            # Visibility is not yet calibrated per capture. Never infer EMPTY
            # solely from missing detections or an empty-facing model output.
            is_visible=False,
            is_occluded=False,
        )
        for cell in sorted(
            planogram.cells,
            key=lambda item: (item.row_index, item.column_index, item.id),
        )
    ]
    observations = compare_detections_to_cells(cells, ordered_detections)
    results = []
    for observation in observations:
        detection_ids = [
            ordered_detections[index].id
            for index in observation.detection_indices
        ]
        results.append({
            "cell_code": observation.cell_id,
            "status": observation.status,
            "expected_product_id": observation.expected_product_id,
            "expected_facings": observation.expected_facings,
            "observed_facings": observation.observed_facings,
            "observed_product_ids": list(observation.observed_product_ids),
            "detection_ids": detection_ids,
            "overlap_ratio": observation.overlap_ratio,
        })
    return results


COMPARISON_SCHEMA_VERSION = 1


def comparison_fingerprint(snapshot: dict) -> str:
    """Return a stable digest for the complete comparison evidence snapshot.

    The digest is an identity/provenance aid, not a digital signature. It is
    deterministic for the same JSON-compatible evidence and schema version.
    """
    payload = {
        "comparison_schema_version": COMPARISON_SCHEMA_VERSION,
        **{key: value for key, value in snapshot.items() if key != "comparison_sha256"},
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
