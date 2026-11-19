"""Versioned shelf planogram lifecycle and conservative geometry validation.

Planograms describe expected facing positions only. They do not represent stock
counts and are never used to mutate inventory.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Iterable, Mapping

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models
from app.shelf_layout import ShelfCell


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ShelfPlanogramError(ValueError):
    """Raised when a planogram cannot be created or transitioned safely."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active_actor(db: Session, actor_user_id: int) -> models.User:
    actor = db.get(models.User, actor_user_id)
    if actor is None or not actor.is_active:
        raise ShelfPlanogramError("An active user is required")
    if actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise ShelfPlanogramError("Only ADMIN or SUPERVISOR may manage planograms")
    return actor


def _lock_source_image(
    db: Session,
    image_id: int | None,
    *,
    shelf_id: int | None = None,
    expected_sha256: str | None = None,
    require_active: bool = True,
) -> models.ShelfImage | None:
    if image_id is None:
        return None
    image = (
        db.query(models.ShelfImage)
        .filter(models.ShelfImage.id == image_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if image is None:
        raise ShelfPlanogramError("Calibration image not found")
    if require_active and image.retention_status != "ACTIVE":
        raise ShelfPlanogramError("Calibration image is not ACTIVE")
    if shelf_id is not None and image.shelf_id != shelf_id:
        raise ShelfPlanogramError("Calibration image must belong to the same shelf")
    if expected_sha256 is not None and image.sha256 != expected_sha256:
        raise ShelfPlanogramError("Calibration image SHA-256 does not match")
    return image


def _lock_shelf(db: Session, shelf_id: int) -> tuple[models.Shelf, int]:
    result = (
        db.query(models.Shelf, models.Zone.store_id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == shelf_id)
        .with_for_update(of=models.Shelf)
        .populate_existing()
        .first()
    )
    if result is None:
        raise ShelfPlanogramError("Shelf not found")
    return result[0], result[1]


def _enforce_store_scope(actor: models.User, store_id: int) -> None:
    if actor.role != "ADMIN" and actor.store_id != store_id:
        raise ShelfPlanogramError("Access to this shelf is not allowed")


def _normalize_reason(reason: str) -> str:
    if not isinstance(reason, str):
        raise ShelfPlanogramError("A reason is required")
    normalized = reason.strip()
    if len(normalized) < 3 or len(normalized) > 500:
        raise ShelfPlanogramError("Reason must contain between 3 and 500 characters")
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in normalized):
        raise ShelfPlanogramError("Reason cannot contain control characters")
    return normalized


def _validate_calibration(
    calibration_source: str,
    calibration_image_id: int | None,
    calibration_image_sha256: str | None,
) -> tuple[str, str | None]:
    source = calibration_source.strip().upper() if isinstance(calibration_source, str) else ""
    if source == "MANUAL":
        if calibration_image_id is not None or calibration_image_sha256 is not None:
            raise ShelfPlanogramError("MANUAL calibration cannot reference an image")
        return source, None
    if source == "IMAGE":
        if calibration_image_id is None or not isinstance(calibration_image_id, int) or isinstance(calibration_image_id, bool):
            raise ShelfPlanogramError("IMAGE calibration requires a positive image ID")
        if calibration_image_id <= 0:
            raise ShelfPlanogramError("IMAGE calibration requires a positive image ID")
        if not isinstance(calibration_image_sha256, str):
            raise ShelfPlanogramError("IMAGE calibration requires the source image SHA-256")
        digest = calibration_image_sha256.strip().lower()
        if not _SHA256_RE.fullmatch(digest):
            raise ShelfPlanogramError("Calibration SHA-256 must be 64 lowercase hexadecimal characters")
        return source, digest
    raise ShelfPlanogramError("calibration_source must be MANUAL or IMAGE")


def _validated_cells(cells: Iterable[Mapping[str, Any] | Any]) -> tuple[dict[str, Any], ...]:
    items = tuple(cells)
    if not items or len(items) > 500:
        raise ShelfPlanogramError("A planogram must contain between 1 and 500 cells")

    normalized: list[dict[str, Any]] = []
    codes: set[str] = set()
    grid_positions: set[tuple[int, int]] = set()
    geometry: list[ShelfCell] = []

    def read(item: Mapping[str, Any] | Any, name: str):
        return item.get(name) if isinstance(item, Mapping) else getattr(item, name, None)

    for item in items:
        code = read(item, "cell_code")
        row = read(item, "row_index")
        column = read(item, "column_index")
        if not isinstance(code, str) or not code.strip() or len(code.strip()) > 80:
            raise ShelfPlanogramError("cell_code must contain between 1 and 80 characters")
        code = code.strip()
        if code in codes:
            raise ShelfPlanogramError("cell_code values must be unique")
        codes.add(code)
        if (
            isinstance(row, bool) or not isinstance(row, int) or row < 0
            or isinstance(column, bool) or not isinstance(column, int) or column < 0
        ):
            raise ShelfPlanogramError("row_index and column_index must be non-negative integers")
        if (row, column) in grid_positions:
            raise ShelfPlanogramError("Grid positions must be unique within a planogram")
        grid_positions.add((row, column))

        expected_product_id = read(item, "expected_product_id")
        expected_facings = read(item, "expected_facings")
        try:
            cell = ShelfCell(
                cell_id=code,
                x_min=read(item, "x_min"),
                y_min=read(item, "y_min"),
                x_max=read(item, "x_max"),
                y_max=read(item, "y_max"),
                expected_product_id=expected_product_id,
                expected_facings=expected_facings,
                is_visible=False,
            )
        except (TypeError, ValueError) as exc:
            raise ShelfPlanogramError(f"Invalid geometry for cell {code}: {exc}") from exc

        geometry.append(cell)
        normalized.append({
            "cell_code": code,
            "row_index": row,
            "column_index": column,
            "x_min": cell.x_min,
            "y_min": cell.y_min,
            "x_max": cell.x_max,
            "y_max": cell.y_max,
            "expected_product_id": expected_product_id,
            "expected_facings": cell.expected_facings,
        })

    for index, cell in enumerate(geometry):
        for other in geometry[index + 1:]:
            width = min(cell.x_max, other.x_max) - max(cell.x_min, other.x_min)
            height = min(cell.y_max, other.y_max) - max(cell.y_min, other.y_min)
            if width > 0 and height > 0:
                raise ShelfPlanogramError("Planogram cells must not overlap")

    return tuple(normalized)


def _validate_cell_products(db: Session, shelf_id: int, cells: tuple[dict[str, Any], ...]) -> None:
    product_ids = {
        cell["expected_product_id"]
        for cell in cells
        if cell["expected_product_id"] is not None
    }
    if not product_ids:
        return
    eligible = {
        row[0]
        for row in (
            db.query(models.ShelfProduct.product_id)
            .join(models.Product, models.Product.id == models.ShelfProduct.product_id)
            .filter(
                models.ShelfProduct.shelf_id == shelf_id,
                models.ShelfProduct.product_id.in_(product_ids),
                models.Product.is_active.is_(True),
            )
            .all()
        )
    }
    if eligible != product_ids:
        raise ShelfPlanogramError("Every expected SKU must be active and assigned to this shelf")


def create_draft_planogram(
    db: Session,
    *,
    shelf_id: int,
    actor_user_id: int,
    cells: Iterable[Mapping[str, Any] | Any],
    calibration_source: str = "MANUAL",
    calibration_image_id: int | None = None,
    calibration_image_sha256: str | None = None,
) -> models.ShelfPlanogram:
    """Create the next immutable-version identity in DRAFT state.

    Lock order is calibration image (when present) -> shelf -> planogram rows.
    """
    actor = _active_actor(db, actor_user_id)
    source, digest = _validate_calibration(
        calibration_source, calibration_image_id, calibration_image_sha256
    )
    normalized_cells = _validated_cells(cells)

    image = None
    if source == "IMAGE":
        image = _lock_source_image(
            db, calibration_image_id, expected_sha256=digest
        )

    shelf, store_id = _lock_shelf(db, shelf_id)
    _enforce_store_scope(actor, store_id)
    if image is not None and image.shelf_id != shelf.id:
        raise ShelfPlanogramError("Calibration image must belong to the same shelf")

    _validate_cell_products(db, shelf.id, normalized_cells)
    latest_version = (
        db.query(func.max(models.ShelfPlanogram.version))
        .filter(models.ShelfPlanogram.shelf_id == shelf.id)
        .scalar()
    ) or 0
    planogram = models.ShelfPlanogram(
        shelf_id=shelf.id,
        version=latest_version + 1,
        status="DRAFT",
        calibration_source=source,
        calibration_image_id=image.id if image is not None else None,
        calibration_image_sha256=digest,
        created_by_user_id=actor.id,
    )
    db.add(planogram)
    db.flush()

    for cell in normalized_cells:
        db.add(models.ShelfPlanogramCell(planogram_id=planogram.id, **cell))
    db.flush()
    return planogram


def replace_draft_planogram_cells(
    db: Session,
    *,
    planogram_id: int,
    actor_user_id: int,
    cells: Iterable[Mapping[str, Any] | Any],
) -> models.ShelfPlanogram:
    """Atomically replace all cells of a DRAFT planogram only."""
    actor = _active_actor(db, actor_user_id)
    normalized_cells = _validated_cells(cells)
    shelf_id, image_id, image_sha256 = _load_planogram_context(db, planogram_id)
    image = _lock_source_image(
        db, image_id, shelf_id=shelf_id, expected_sha256=image_sha256
    ) if image_id is not None else None
    shelf, store_id = _lock_shelf(db, shelf_id)
    _enforce_store_scope(actor, store_id)
    planogram = (
        db.query(models.ShelfPlanogram)
        .filter(models.ShelfPlanogram.id == planogram_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if planogram is None:
        raise ShelfPlanogramError("Planogram not found")
    if planogram.status != "DRAFT":
        raise ShelfPlanogramError("Only a DRAFT planogram can change cells")
    if image is not None and (
        image.shelf_id != shelf.id
        or image.retention_status != "ACTIVE"
        or image.sha256 != planogram.calibration_image_sha256
    ):
        raise ShelfPlanogramError("Calibration image is no longer eligible")
    _validate_cell_products(db, shelf.id, normalized_cells)
    db.query(models.ShelfPlanogramCell).filter(
        models.ShelfPlanogramCell.planogram_id == planogram.id
    ).delete(synchronize_session=False)
    for cell in normalized_cells:
        db.add(models.ShelfPlanogramCell(planogram_id=planogram.id, **cell))
    db.flush()
    db.expire(planogram, ["cells"])
    return planogram


def _load_planogram_context(
    db: Session, planogram_id: int
) -> tuple[int, int | None, str | None]:
    row = (
        db.query(
            models.ShelfPlanogram.shelf_id,
            models.ShelfPlanogram.calibration_image_id,
            models.ShelfPlanogram.calibration_image_sha256,
        )
        .filter(models.ShelfPlanogram.id == planogram_id)
        .first()
    )
    if row is None:
        raise ShelfPlanogramError("Planogram not found")
    return row[0], row[1], row[2]


def activate_planogram(
    db: Session,
    *,
    planogram_id: int,
    actor_user_id: int,
    reason: str,
) -> models.ShelfPlanogram:
    """Activate a draft and retire the previous active version atomically."""
    actor = _active_actor(db, actor_user_id)
    shelf_id, image_id, image_sha256 = _load_planogram_context(db, planogram_id)
    image = _lock_source_image(
        db, image_id, shelf_id=shelf_id, expected_sha256=image_sha256
    ) if image_id is not None else None

    shelf, store_id = _lock_shelf(db, shelf_id)
    _enforce_store_scope(actor, store_id)
    planogram = (
        db.query(models.ShelfPlanogram)
        .filter(models.ShelfPlanogram.id == planogram_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if planogram is None:
        raise ShelfPlanogramError("Planogram not found")
    if planogram.status != "DRAFT":
        raise ShelfPlanogramError("Only a DRAFT planogram can be activated")
    if image is not None and (
        image.shelf_id != shelf.id
        or image.retention_status != "ACTIVE"
        or image.sha256 != planogram.calibration_image_sha256
    ):
        raise ShelfPlanogramError("Calibration image is no longer eligible")
    if not planogram.cells:
        raise ShelfPlanogramError("A planogram must contain at least one cell")
    cell_payload = tuple({
        "expected_product_id": cell.expected_product_id
    } for cell in planogram.cells)
    _validate_cell_products(db, shelf.id, cell_payload)

    normalized_reason = _normalize_reason(reason)
    now = _now()
    previous = (
        db.query(models.ShelfPlanogram)
        .filter(
            models.ShelfPlanogram.shelf_id == shelf.id,
            models.ShelfPlanogram.status == "ACTIVE",
        )
        .with_for_update()
        .populate_existing()
        .first()
    )
    if previous is not None:
        previous.status = "RETIRED"
        previous.retired_by_user_id = actor.id
        previous.retired_at = now
        previous.retirement_reason = normalized_reason

    planogram.status = "ACTIVE"
    planogram.activated_by_user_id = actor.id
    planogram.activated_at = now
    planogram.activation_reason = normalized_reason
    db.flush()
    return planogram


def retire_planogram(
    db: Session,
    *,
    planogram_id: int,
    actor_user_id: int,
    reason: str,
) -> models.ShelfPlanogram:
    """Retire an active planogram without deleting its history."""
    actor = _active_actor(db, actor_user_id)
    shelf_id, image_id, image_sha256 = _load_planogram_context(db, planogram_id)
    image = _lock_source_image(
        db, image_id, shelf_id=shelf_id, expected_sha256=image_sha256, require_active=False
    ) if image_id is not None else None
    shelf, store_id = _lock_shelf(db, shelf_id)
    _enforce_store_scope(actor, store_id)
    planogram = (
        db.query(models.ShelfPlanogram)
        .filter(models.ShelfPlanogram.id == planogram_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if planogram is None:
        raise ShelfPlanogramError("Planogram not found")
    if planogram.status != "ACTIVE":
        raise ShelfPlanogramError("Only an ACTIVE planogram can be retired")
    if image is not None and (
        image.shelf_id != shelf.id
        or image.sha256 != planogram.calibration_image_sha256
    ):
        raise ShelfPlanogramError("Calibration image identity no longer matches the planogram")
    planogram.status = "RETIRED"
    planogram.retired_by_user_id = actor.id
    planogram.retired_at = _now()
    planogram.retirement_reason = _normalize_reason(reason)
    db.flush()
    return planogram


def load_active_planogram_for_shelf(
    db: Session, *, shelf_id: int, actor_user_id: int
) -> models.ShelfPlanogram | None:
    """Load the active version only after revalidating its calibration source."""
    actor = _active_actor(db, actor_user_id)
    row = (
        db.query(
            models.ShelfPlanogram.id,
            models.ShelfPlanogram.calibration_image_id,
            models.ShelfPlanogram.calibration_image_sha256,
        )
        .filter(
            models.ShelfPlanogram.shelf_id == shelf_id,
            models.ShelfPlanogram.status == "ACTIVE",
        )
        .first()
    )
    if row is None:
        return None
    image = _lock_source_image(
        db, row.calibration_image_id, shelf_id=shelf_id, expected_sha256=row.calibration_image_sha256
    ) if row.calibration_image_id is not None else None
    shelf, store_id = _lock_shelf(db, shelf_id)
    _enforce_store_scope(actor, store_id)
    planogram = (
        db.query(models.ShelfPlanogram)
        .filter(
            models.ShelfPlanogram.id == row.id,
            models.ShelfPlanogram.status == "ACTIVE",
        )
        .with_for_update()
        .populate_existing()
        .first()
    )
    if planogram is None:
        return None
    if image is not None and (
        image.shelf_id != shelf.id
        or image.retention_status != "ACTIVE"
        or image.sha256 != planogram.calibration_image_sha256
    ):
        raise ShelfPlanogramError("Active planogram calibration source is no longer eligible")
    _validate_cell_products(
        db,
        shelf.id,
        tuple({"expected_product_id": cell.expected_product_id} for cell in planogram.cells),
    )
    return planogram
