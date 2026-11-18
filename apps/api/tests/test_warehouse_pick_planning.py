from decimal import Decimal

import pytest

from app.warehouse_pick_planning import build_warehouse_pick_plan


def candidate(product=1, shelf=10, quantity=8, temperature="AMBIENT", allowed=True):
    return {
        "product_id": product,
        "shelf_id": shelf,
        "suggested_quantity": quantity,
        "temperature_requirement": temperature,
        "task_creation_allowed": allowed,
    }


def placement(product, location, quantity, distance, temperature="AMBIENT", aisle="A"):
    return {
        "product_id": product,
        "location_id": location,
        "location_code": f"L-{location}",
        "aisle": aisle,
        "rack": "R1",
        "bin_code": f"B{location}",
        "distance_to_picking_m": distance,
        "temperature_zone": temperature,
        "quantity": quantity,
        "is_active": True,
    }


def test_pick_plan_aggregates_same_sku_and_uses_nearest_compatible_locations():
    result = build_warehouse_pick_plan(
        [candidate(shelf=10, quantity=5), candidate(shelf=11, quantity=6)],
        [
            placement(1, 1, 4, 3),
            placement(1, 2, 10, 8),
            placement(1, 3, 100, 1, temperature="CHILLED"),
        ],
    )

    assert result["status"] == "READY_FOR_REVIEW"
    assert result["products"][0]["required_quantity"] == 11
    assert result["products"][0]["allocated_quantity"] == 11
    assert [row["location_id"] for row in result["allocations"]] == [1, 2]
    assert result["summary"]["warehouse_stops"] == 2
    assert result["stock_reserved"] is False
    assert result["stock_movement_allowed"] is False


def test_pick_plan_reports_shortfall_without_overallocating():
    result = build_warehouse_pick_plan(
        [candidate(quantity=12)],
        [placement(1, 1, 7, 2)],
    )

    product = result["products"][0]
    assert result["status"] == "PARTIAL_OR_BLOCKED"
    assert product["allocated_quantity"] == 7
    assert product["shortfall_quantity"] == 5
    assert product["status"] == "PARTIAL_STOCK"


def test_pick_plan_does_not_mix_temperature_zones():
    result = build_warehouse_pick_plan(
        [candidate(temperature="FROZEN")],
        [placement(1, 1, 20, 1, temperature="AMBIENT")],
    )

    product = result["products"][0]
    assert product["status"] == "NO_COMPATIBLE_STOCK"
    assert product["allocated_quantity"] == 0
    assert result["allocations"] == []


def test_pick_plan_blocks_when_product_temperature_profile_is_unknown():
    result = build_warehouse_pick_plan(
        [candidate(temperature=None)],
        [placement(1, 1, 20, 1)],
    )

    assert result["products"][0]["status"] == "PROFILE_UNKNOWN"
    assert result["allocations"] == []


def test_pick_plan_does_not_create_demand_from_unquantified_candidates():
    result = build_warehouse_pick_plan(
        [candidate(quantity=None), candidate(shelf=11, quantity=8, allowed=False)],
        [placement(1, 1, 100, 1)],
    )

    assert result["status"] == "NO_QUANTIFIED_DEMAND"
    assert result["products"] == []
    assert result["candidates_without_quantified_demand"] == 2


def test_pick_plan_ignores_invalid_or_inactive_placement_rows():
    result = build_warehouse_pick_plan(
        [candidate(quantity=5)],
        [
            placement(1, 1, True, 1),
            {**placement(1, 2, 20, 2), "is_active": False},
            placement(1, 3, 2, 3),
        ],
    )

    assert result["products"][0]["allocated_quantity"] == 2
    assert result["products"][0]["shortfall_quantity"] == 3


def test_pick_plan_groups_items_by_location_and_sequences_stops():
    result = build_warehouse_pick_plan(
        [candidate(product=1, quantity=2), candidate(product=2, shelf=20, quantity=3)],
        [placement(1, 1, 5, 4), placement(2, 1, 5, 4)],
    )

    assert result["summary"]["warehouse_stops"] == 1
    assert len(result["stops"][0]["items"]) == 2
    assert result["stops"][0]["sequence"] == 1
    assert result["physical_route_optimized"] is False


def test_pick_plan_excludes_all_duplicate_product_location_rows_to_prevent_double_counting():
    result = build_warehouse_pick_plan(
        [candidate(quantity=9)],
        [
            placement(1, 1, 8, 2),
            placement(1, 1, 8, 2),
            placement(1, 2, 2, 4),
        ],
    )

    product = result["products"][0]
    assert product["required_quantity"] == 9
    assert product["allocated_quantity"] == 2
    assert product["shortfall_quantity"] == 7
    assert product["status"] == "PARTIAL_STOCK"
    assert [row["location_id"] for row in result["allocations"]] == [2]
    assert result["summary"]["ambiguous_placement_rows_excluded"] == 2


def test_pick_plan_does_not_flag_same_location_for_different_products_as_duplicate():
    result = build_warehouse_pick_plan(
        [
            candidate(product=1, quantity=2),
            candidate(product=2, shelf=20, quantity=3),
        ],
        [
            placement(1, 1, 2, 1),
            placement(2, 1, 3, 1),
        ],
    )

    assert [row["status"] for row in result["products"]] == [
        "READY_FOR_REVIEW", "READY_FOR_REVIEW"
    ]
    assert result["summary"]["ambiguous_placement_rows_excluded"] == 0


def test_pick_plan_accepts_decimal_quantities_returned_by_sqlalchemy_numeric():
    result = build_warehouse_pick_plan(
        [candidate(quantity=Decimal("4.500"))],
        [placement(1, 1, Decimal("5.250"), Decimal("2.00"))],
    )
    assert result["products"][0]["status"] == "READY_FOR_REVIEW"
    assert result["allocations"][0]["proposed_pick_quantity"] == 4.5
