"""Deterministic shelf-row grouping from normalized product detections.

This module estimates visible positions only. It does not infer stock depth,
missing inventory, or total units behind the front-facing products.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any


@dataclass(frozen=True)
class ShelfPosition:
    detection_index: int
    product_id: int | None
    center_x: float
    center_y: float


@dataclass(frozen=True)
class ShelfRow:
    row_index: int
    y_min: float
    y_max: float
    positions: tuple[ShelfPosition, ...]

    @property
    def visible_facings(self) -> int:
        """Count detected front-facing objects, not units stored in depth."""
        return len(self.positions)


def _read_box(item: Any) -> tuple[float, float, float, float, int | None]:
    def value(name: str):
        return item.get(name) if isinstance(item, Mapping) else getattr(item, name)

    x1, y1, x2, y2 = (float(value(key)) for key in ("x_min", "y_min", "x_max", "y_max"))
    product_id = value("product_id")
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError("Detection coordinates must be valid and normalized to [0, 1]")
    if product_id is not None and (
        isinstance(product_id, bool)
        or not isinstance(product_id, int)
        or product_id <= 0
    ):
        raise ValueError("product_id must be a positive integer or None")
    return x1, y1, x2, y2, int(product_id) if product_id is not None else None


def group_detections_into_rows(
    detections: Iterable[Any],
    *,
    minimum_vertical_overlap: float = 0.35,
) -> tuple[ShelfRow, ...]:
    """Group boxes into rows using vertical overlap over the smaller box height.

    The threshold is a geometric heuristic and must be validated against
    annotated images from the target store/camera.
    """
    if not 0 < minimum_vertical_overlap <= 1:
        raise ValueError("minimum_vertical_overlap must be in (0, 1]")

    boxes = []
    for index, item in enumerate(detections):
        x1, y1, x2, y2, product_id = _read_box(item)
        boxes.append({
            "index": index, "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2,
            "product_id": product_id,
        })

    # Stable top-to-bottom processing; assign to the row with strongest overlap.
    boxes.sort(key=lambda box: (box["cy"], box["cx"], box["index"]))
    rows: list[list[dict[str, Any]]] = []
    for box in boxes:
        best_row = None
        best_overlap = 0.0
        for row in rows:
            row_top = min(item["y1"] for item in row)
            row_bottom = max(item["y2"] for item in row)
            intersection = max(0.0, min(box["y2"], row_bottom) - max(box["y1"], row_top))
            smaller_height = min(box["y2"] - box["y1"], row_bottom - row_top)
            overlap = intersection / smaller_height if smaller_height > 0 else 0.0
            if overlap >= minimum_vertical_overlap and overlap > best_overlap:
                best_row, best_overlap = row, overlap
        if best_row is None:
            rows.append([box])
        else:
            best_row.append(box)

    rows.sort(key=lambda row: sum(item["cy"] for item in row) / len(row))
    result = []
    for row_index, row in enumerate(rows):
        ordered = sorted(row, key=lambda item: (item["cx"], item["index"]))
        result.append(ShelfRow(
            row_index=row_index,
            y_min=min(item["y1"] for item in row),
            y_max=max(item["y2"] for item in row),
            positions=tuple(ShelfPosition(
                detection_index=item["index"],
                product_id=item["product_id"],
                center_x=item["cx"],
                center_y=item["cy"],
            ) for item in ordered),
        ))
    return tuple(result)



@dataclass(frozen=True)
class ShelfCell:
    """Expected display cell supplied by a reviewed planogram or calibration."""

    cell_id: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    expected_product_id: int | None = None
    is_visible: bool = False
    is_occluded: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.cell_id, str) or not self.cell_id.strip():
            raise ValueError("cell_id must be a non-empty string")
        if not (
            0 <= self.x_min < self.x_max <= 1
            and 0 <= self.y_min < self.y_max <= 1
        ):
            raise ValueError("Shelf cell coordinates must be normalized and non-degenerate")
        if self.expected_product_id is not None and (
            isinstance(self.expected_product_id, bool)
            or not isinstance(self.expected_product_id, int)
            or self.expected_product_id <= 0
        ):
            raise ValueError("expected_product_id must be a positive integer or None")
        if not isinstance(self.is_visible, bool) or not isinstance(self.is_occluded, bool):
            raise ValueError("Cell visibility flags must be booleans")


@dataclass(frozen=True)
class ShelfCellObservation:
    cell_id: str
    status: str
    expected_product_id: int | None
    observed_product_ids: tuple[int | None, ...]
    detection_indices: tuple[int, ...]
    overlap_ratio: float


def compare_detections_to_cells(
    cells: Iterable[ShelfCell],
    detections: Iterable[Any],
    *,
    minimum_cell_overlap: float = 0.25,
) -> tuple[ShelfCellObservation, ...]:
    """Compare detections with explicit, calibrated cells.

    An undetected cell is called EMPTY only when it is explicitly visible and
    not marked occluded. This function never estimates stock depth or changes
    inventory; missing/uncertain geometry must be represented as UNKNOWN.
    """
    if not 0 < minimum_cell_overlap <= 1:
        raise ValueError("minimum_cell_overlap must be in (0, 1]")

    cell_list = tuple(cells)
    if len({cell.cell_id for cell in cell_list}) != len(cell_list):
        raise ValueError("Shelf cell IDs must be unique")

    detection_boxes = []
    for index, detection in enumerate(detections):
        x1, y1, x2, y2, product_id = _read_box(detection)
        detection_boxes.append((index, x1, y1, x2, y2, product_id))

    observations = []
    for cell in cell_list:
        cell_area = (cell.x_max - cell.x_min) * (cell.y_max - cell.y_min)
        matches = []
        strongest_overlap = 0.0
        for index, x1, y1, x2, y2, product_id in detection_boxes:
            intersection_width = max(0.0, min(cell.x_max, x2) - max(cell.x_min, x1))
            intersection_height = max(0.0, min(cell.y_max, y2) - max(cell.y_min, y1))
            overlap = (intersection_width * intersection_height) / cell_area
            if overlap >= minimum_cell_overlap:
                matches.append((index, product_id))
                strongest_overlap = max(strongest_overlap, overlap)

        product_ids = tuple(sorted(
            {product_id for _, product_id in matches},
            key=lambda value: (value is None, value if value is not None else 0),
        ))
        detection_indices = tuple(index for index, _ in matches)

        if matches:
            known_ids = {product_id for _, product_id in matches if product_id is not None}
            if cell.expected_product_id is not None and known_ids and cell.expected_product_id not in known_ids:
                status = "MISPLACED"
            elif any(product_id is None for _, product_id in matches) and not known_ids:
                status = "OCCUPIED_UNIDENTIFIED"
            else:
                status = "OCCUPIED"
        elif not cell.is_visible or cell.is_occluded:
            status = "UNKNOWN"
        else:
            status = "EMPTY"

        observations.append(ShelfCellObservation(
            cell_id=cell.cell_id,
            status=status,
            expected_product_id=cell.expected_product_id,
            observed_product_ids=product_ids,
            detection_indices=detection_indices,
            overlap_ratio=round(strongest_overlap, 6),
        ))

    return tuple(observations)
