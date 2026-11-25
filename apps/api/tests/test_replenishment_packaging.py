from decimal import Decimal

from app.replenishment_packaging import build_replenishment_packaging_plan


def levels():
    return [
        {
            "code": "UNIT", "name": "Unidade", "package_type": "UNIT",
            "base_units_per_package": Decimal("1.000"), "is_replenishment_unit": False,
        },
        {
            "code": "CASE", "name": "Caixa", "package_type": "CASE",
            "base_units_per_package": Decimal("12.000"), "is_replenishment_unit": True,
        },
        {
            "code": "PALLET", "name": "Palete", "package_type": "PALLET",
            "base_units_per_package": Decimal("720.000"), "is_replenishment_unit": False,
        },
    ]


def test_replenishment_packaging_plan_proposes_all_packaging_levels_in_base_unit():
    result = build_replenishment_packaging_plan(
        task_creation_allowed=True,
        suggested_quantity=Decimal("20.125"),
        base_unit="kg",
        packaging_levels=levels(),
    )

    assert result["status"] == "AVAILABLE"
    assert result["base_unit"] == "kg"
    assert result["quantity_basis"] == "PRODUCT_BASE_UNIT"
    assert result["preferred_replenishment_packaging_code"] == "CASE"
    assert result["automatic_stock_movement_allowed"] is False
    assert result["stock_reserved"] is False

    unit, case, pallet = result["options"]
    assert unit["package_count"] == 21
    assert unit["planned_base_units_exact"] == "21.000"
    assert case["package_count"] == 2
    assert case["planned_base_units_exact"] == "24.000"
    assert case["excess_base_units_exact"] == "3.875"
    assert case["preferred_for_replenishment"] is True
    assert pallet["package_count"] == 1
    assert pallet["planned_base_units_exact"] == "720.000"


def test_replenishment_packaging_plan_does_not_invent_options_when_not_configured():
    result = build_replenishment_packaging_plan(
        task_creation_allowed=True,
        suggested_quantity=5,
        base_unit="un",
        packaging_levels=[],
    )
    assert result["status"] == "NOT_CONFIGURED"
    assert result["options"] == []
    assert result["automatic_stock_movement_allowed"] is False


def test_replenishment_packaging_plan_is_not_actionable_without_quantified_task():
    result = build_replenishment_packaging_plan(
        task_creation_allowed=False,
        suggested_quantity=None,
        base_unit="un",
        packaging_levels=levels(),
    )
    assert result["status"] == "NOT_ACTIONABLE"
    assert result["options"] == []
