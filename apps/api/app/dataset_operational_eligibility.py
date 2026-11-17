"""Operational eligibility checks for internal dataset image provenance.

The caller must keep the supplied SQLAlchemy transaction open until the
release decision is committed. Image rows are locked in ascending ID order.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Shelf, ShelfImage, Zone


def validate_internal_image_eligibility(
    db: Session | None,
    provenance_entries: list[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    """Verify internal image ownership, SHA-256 and retention under row locks."""
    internal = [
        (index, entry)
        for index, entry in enumerate(provenance_entries)
        if isinstance(entry, dict) and entry.get("source_type") == "internal"
    ]
    report: dict[str, Any] = {
        "status": "APPROVED",
        "internal_images": len(internal),
        "checked_images": 0,
        "locked_image_ids": [],
    }
    if not internal:
        return [], report
    if db is None:
        errors = ["database session is required for internal image provenance"]
        report.update({"status": "BLOCKED", "errors": errors})
        return errors, report

    errors: list[str] = []
    ids: set[int] = set()
    for index, entry in internal:
        image_id = entry.get("shelf_image_id")
        if isinstance(image_id, int) and not isinstance(image_id, bool) and image_id > 0:
            ids.add(image_id)
        else:
            errors.append(f"images[{index}].shelf_image_id is invalid for operational lookup")
    if errors:
        report.update({"status": "BLOCKED", "errors": errors})
        return errors, report

    statement = (
        select(ShelfImage, Zone.store_id)
        .join(Shelf, Shelf.id == ShelfImage.shelf_id)
        .join(Zone, Zone.id == Shelf.zone_id)
        .where(ShelfImage.id.in_(sorted(ids)))
        .order_by(ShelfImage.id.asc())
        .with_for_update(of=ShelfImage)
    )
    rows = db.execute(statement).all()
    actual = {image.id: (image, store_id) for image, store_id in rows}
    report["locked_image_ids"] = sorted(actual)
    report["checked_images"] = len(actual)

    for index, entry in internal:
        image_id = entry["shelf_image_id"]
        result = actual.get(image_id)
        if result is None:
            errors.append(f"images[{index}]: internal shelf image {image_id} does not exist")
            continue
        image, actual_store_id = result
        if entry.get("store_id") != actual_store_id:
            errors.append(
                f"images[{index}]: shelf image {image_id} does not belong to declared store_id"
            )
        if entry.get("source_image_sha256") != image.sha256:
            errors.append(
                f"images[{index}]: source_image_sha256 does not match operational shelf image {image_id}"
            )
        if image.retention_status != "ACTIVE":
            errors.append(
                f"images[{index}]: shelf image {image_id} is not ACTIVE "
                f"(status={image.retention_status})"
            )
        if image.legal_hold:
            errors.append(f"images[{index}]: shelf image {image_id} is under legal hold")

    report.update({
        "status": "APPROVED" if not errors else "BLOCKED",
        "errors": errors,
    })
    return errors, report
