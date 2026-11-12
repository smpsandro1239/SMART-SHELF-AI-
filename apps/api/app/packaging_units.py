"""Unit-of-measure conversions and replenishment pack calculations."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Mapping


def _positive_decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be a valid positive number")
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{field} must be a valid positive number")
    return result


def convert_to_base_units(package_quantity: Any, base_units_per_package: Any) -> Decimal:
    """Convert a pack count (e.g. 2 cases) to the product's base unit count."""
    quantity = _positive_decimal(package_quantity, "package_quantity")
    factor = _positive_decimal(base_units_per_package, "base_units_per_package")
    return quantity * factor


def calculate_replenishment_packs(
    *,
    required_base_units: Any,
    base_units_per_package: Any,
    allow_open_package: bool = False,
    base_unit_replenishment_available: bool = False,
) -> dict[str, Any]:
    """Calculate whole packs and optional loose base units without losing quantity."""
    try:
        required = _positive_decimal(required_base_units, "required_base_units")
        pack_size = _positive_decimal(base_units_per_package, "base_units_per_package")
    except ValueError:
        raise

    if not isinstance(allow_open_package, bool):
        raise ValueError("allow_open_package must be boolean")
    if not isinstance(base_unit_replenishment_available, bool):
        raise ValueError("base_unit_replenishment_available must be boolean")
    if allow_open_package and not base_unit_replenishment_available:
        raise ValueError("Opening a pack requires an active base-unit replenishment level")

    if allow_open_package:
        whole_packs = int((required / pack_size).to_integral_value(rounding=ROUND_FLOOR))
        loose_units = required - (pack_size * whole_packs)
        moved_base_units = required
    else:
        whole_packs = int((required / pack_size).to_integral_value(rounding=ROUND_CEILING))
        loose_units = Decimal("0")
        moved_base_units = pack_size * whole_packs

    excess = moved_base_units - required
    return {
        "required_base_units": float(required),
        "package_count": whole_packs,
        "loose_base_units": float(loose_units),
        "planned_base_units": float(moved_base_units),
        "excess_base_units": float(excess),
        "opened_package_required": bool(loose_units > 0),
        "exact_quantity_possible": excess == 0,
        "automatic_stock_movement_allowed": False,
    }
