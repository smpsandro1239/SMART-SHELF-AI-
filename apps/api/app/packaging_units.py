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


def _require_three_decimal_places(value: Decimal, field: str) -> None:
    try:
        quantized = value.quantize(Decimal("0.001"))
    except InvalidOperation as exc:
        raise ValueError(f"{field} exceeds supported decimal precision") from exc
    if value != quantized:
        raise ValueError(f"{field} supports at most three decimal places")


def convert_to_base_units(package_quantity: Any, base_units_per_package: Any) -> Decimal:
    """Convert a pack count (e.g. 2 cases) to the product's base unit count."""
    quantity = _positive_decimal(package_quantity, "package_quantity")
    factor = _positive_decimal(base_units_per_package, "base_units_per_package")
    _require_three_decimal_places(factor, "base_units_per_package")
    result = quantity * factor
    _require_three_decimal_places(result, "converted_base_units")
    return result


def calculate_replenishment_packs(
    *,
    required_base_units: Any,
    base_units_per_package: Any,
    allow_open_package: bool = False,
) -> dict[str, Any]:
    """Calculate sealed packs and, when allowed, one opened pack supplying loose base units."""
    try:
        required = _positive_decimal(required_base_units, "required_base_units")
        pack_size = _positive_decimal(base_units_per_package, "base_units_per_package")
        _require_three_decimal_places(required, "required_base_units")
        _require_three_decimal_places(pack_size, "base_units_per_package")
    except ValueError:
        raise

    if not isinstance(allow_open_package, bool):
        raise ValueError("allow_open_package must be boolean")
    if allow_open_package:
        whole_packs = int((required / pack_size).to_integral_value(rounding=ROUND_FLOOR))
        loose_units = required - (pack_size * whole_packs)
        opened_pack_count = 1 if loose_units > 0 else 0
        moved_base_units = required
    else:
        whole_packs = int((required / pack_size).to_integral_value(rounding=ROUND_CEILING))
        loose_units = Decimal("0")
        opened_pack_count = 0
        moved_base_units = pack_size * whole_packs

    excess = moved_base_units - required
    return {
        "required_base_units": float(required),
        "required_base_units_exact": format(required, "f"),
        "package_count": whole_packs,
        "opened_package_count": opened_pack_count,
        "loose_base_units": float(loose_units),
        "loose_base_units_exact": format(loose_units, "f"),
        "planned_base_units": float(moved_base_units),
        "planned_base_units_exact": format(moved_base_units, "f"),
        "excess_base_units": float(excess),
        "excess_base_units_exact": format(excess, "f"),
        "opened_package_required": bool(loose_units > 0),
        "exact_quantity_possible": excess == 0,
        "automatic_stock_movement_allowed": False,
    }
