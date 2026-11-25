"""Read-only packaging options attached to replenishment recommendations."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping

from app.packaging_units import calculate_replenishment_packs


def build_replenishment_packaging_plan(
    *,
    task_creation_allowed: bool,
    suggested_quantity: Any,
    base_unit: str | None,
    packaging_levels: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return sealed-pack options in the product base unit; never reserve or move stock."""
    common = {
        "base_unit": base_unit,
        "quantity_basis": "PRODUCT_BASE_UNIT",
        "automatic_stock_movement_allowed": False,
        "stock_reserved": False,
    }
    if not task_creation_allowed or isinstance(suggested_quantity, bool) or suggested_quantity is None:
        return {**common, "status": "NOT_ACTIONABLE", "options": []}

    required = Decimal(str(suggested_quantity))
    if not required.is_finite() or required <= 0:
        return {**common, "status": "NOT_ACTIONABLE", "options": []}

    levels = sorted(
        (dict(level) for level in packaging_levels),
        key=lambda level: (
            Decimal(str(level["base_units_per_package"])),
            str(level.get("code") or "").casefold(),
        ),
    )
    if not levels:
        return {**common, "status": "NOT_CONFIGURED", "options": []}

    options: list[dict[str, Any]] = []
    preferred_code: str | None = None
    for level in levels:
        result = calculate_replenishment_packs(
            required_base_units=required,
            base_units_per_package=level["base_units_per_package"],
            allow_open_package=False,
        )
        preferred = level.get("is_replenishment_unit") is True
        if preferred and preferred_code is None:
            preferred_code = str(level["code"])
        options.append({
            "packaging_code": str(level["code"]),
            "packaging_name": str(level["name"]),
            "package_type": str(level["package_type"]),
            "base_units_per_package": float(level["base_units_per_package"]),
            "base_units_per_package_exact": format(
                Decimal(str(level["base_units_per_package"])), "f"
            ),
            "preferred_for_replenishment": preferred,
            "allow_open_package": False,
            **result,
        })

    return {
        **common,
        "status": "AVAILABLE",
        "required_base_units": float(required),
        "required_base_units_exact": format(required, "f"),
        "preferred_replenishment_packaging_code": preferred_code,
        "options": options,
    }
