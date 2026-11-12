import pytest

from app.warehouse_slotting import recommend_warehouse_slotting


def row(product_id, total, days=28, expected=28, name=None):
    return {
        "product_id": product_id,
        "product_name": name or f"Produto {product_id}",
        "total_quantity": total,
        "history_days": days,
        "expected_days": expected,
    }


def test_high_rotation_product_is_flagged_for_review_near_picking_area():
    result = recommend_warehouse_slotting([
        row(1, 280),
        row(2, 56),
        row(3, 28),
        row(4, 0),
    ])

    first = result.products[0]
    assert first["product_id"] == 1
    assert first["average_daily_sales"] == 10
    assert first["rotation_band"] == "HIGH"
    assert first["recommendation"] == "CONSIDER_NEAR_PICKING_AREA"
    assert first["automatic_relocation_allowed"] is False


def test_incomplete_daily_history_is_excluded_not_treated_as_zero_sales():
    result = recommend_warehouse_slotting([
        row(1, 280, days=27),
        row(2, 56),
    ])

    assert result.analysed_products == 1
    assert result.excluded_incomplete_history == 1
    assert result.products[0]["product_id"] == 2


def test_absolute_minimum_prevents_high_label_for_slow_storewide_sales():
    result = recommend_warehouse_slotting(
        [row(1, 14), row(2, 7), row(3, 0)],
        minimum_average_daily_sales=2,
    )

    assert all(item["rotation_band"] != "HIGH" for item in result.products)
    assert all(item["recommendation"] == "KEEP_CURRENT_LOCATION_PENDING_REVIEW" for item in result.products)


@pytest.mark.parametrize("threshold", [-1, float("nan"), float("inf"), True, "1"])
def test_rejects_invalid_minimum_average_daily_sales(threshold):
    with pytest.raises(ValueError):
        recommend_warehouse_slotting([], minimum_average_daily_sales=threshold)


from app.warehouse_slotting import recommend_physical_slot


def profile(**overrides):
    value = {
        "unit_volume_cm3": 100,
        "unit_weight_kg": 0.5,
        "temperature_requirement": "AMBIENT",
        "is_fragile": False,
        "requires_segregation": False,
    }
    value.update(overrides)
    return value


def location(code, distance, **overrides):
    value = {
        "location_id": 1,
        "code": code,
        "distance_to_picking_m": distance,
        "max_volume_cm3": 10000,
        "max_weight_kg": 100,
        "occupied_volume_cm3": 0,
        "occupied_weight_kg": 0,
        "temperature_zone": "AMBIENT",
        "is_active": True,
        "other_product_count": 0,
    }
    value.update(overrides)
    return value


def test_physical_slotting_prefers_nearest_feasible_location():
    result = recommend_physical_slot(
        product_id=7,
        required_quantity=10,
        product_profile=profile(),
        locations=[location("B-02", 18), location("A-01", 4)],
    )

    assert result.status == "CANDIDATES_FOUND"
    assert result.candidates[0]["location_code"] == "A-01"
    assert result.candidates[0]["required_volume_cm3"] == 1000
    assert result.candidates[0]["automatic_movement_allowed"] is False


def test_physical_slotting_rejects_temperature_mismatch():
    result = recommend_physical_slot(
        product_id=7,
        required_quantity=2,
        product_profile=profile(temperature_requirement="FROZEN"),
        locations=[location("AMBIENT-01", 2)],
    )

    assert result.status == "NO_COMPATIBLE_LOCATION"
    assert result.rejected_locations[0]["reason"] == "TEMPERATURE_INCOMPATIBLE"


def test_physical_slotting_rejects_insufficient_volume_and_weight():
    result = recommend_physical_slot(
        product_id=7,
        required_quantity=10,
        product_profile=profile(),
        locations=[
            location("SMALL-V", 1, max_volume_cm3=500),
            location("SMALL-W", 2, max_weight_kg=2),
        ],
    )

    assert result.status == "NO_COMPATIBLE_LOCATION"
    assert {item["reason"] for item in result.rejected_locations} == {
        "INSUFFICIENT_VOLUME_CAPACITY", "INSUFFICIENT_WEIGHT_CAPACITY"
    }


def test_segregation_requirement_rejects_mixed_sku_location():
    result = recommend_physical_slot(
        product_id=7,
        required_quantity=1,
        product_profile=profile(requires_segregation=True),
        locations=[location("MIXED", 1, other_product_count=2)],
    )

    assert result.rejected_locations[0]["reason"] == "SEGREGATION_REQUIRED"


def test_missing_profile_does_not_guess_a_location():
    result = recommend_physical_slot(
        product_id=7,
        required_quantity=1,
        product_profile=None,
        locations=[location("A-01", 1)],
    )

    assert result.status == "PRODUCT_PROFILE_REQUIRED"
    assert result.candidates == ()


@pytest.mark.parametrize("quantity", [0, -1, float("nan"), True])
def test_physical_slotting_rejects_invalid_required_quantity(quantity):
    with pytest.raises(ValueError):
        recommend_physical_slot(
            product_id=7,
            required_quantity=quantity,
            product_profile=profile(),
            locations=[],
        )


def test_physical_slotting_rejects_unknown_current_occupancy():
    result = recommend_physical_slot(
        product_id=7,
        required_quantity=1,
        product_profile=profile(),
        locations=[location("UNKNOWN-OCCUPANCY", 1, occupied_volume_cm3=None, occupied_weight_kg=None)],
    )

    assert result.status == "NO_COMPATIBLE_LOCATION"
    assert result.rejected_locations[0]["reason"] == "UNKNOWN_CURRENT_OCCUPANCY"



def test_slotting_accepts_decimal_sales_from_sqlalchemy_numeric():
    from decimal import Decimal

    result = recommend_warehouse_slotting([
        row(1, Decimal("280.500")),
        row(2, Decimal("56.250")),
        row(3, Decimal("28.000")),
        row(4, Decimal("0.000")),
    ])

    assert result.analysed_products == 4
    assert result.products[0]["product_id"] == 1
    assert result.products[0]["average_daily_sales"] == 10.018


def test_physical_slotting_accepts_decimal_database_measurements():
    from decimal import Decimal

    result = recommend_physical_slot(
        product_id=7,
        required_quantity=Decimal("2.500"),
        product_profile=profile(
            unit_volume_cm3=Decimal("100.00"),
            unit_weight_kg=Decimal("0.500"),
        ),
        locations=[location(
            "A-01",
            Decimal("2.00"),
            max_volume_cm3=Decimal("1000.00"),
            max_weight_kg=Decimal("10.000"),
            occupied_volume_cm3=Decimal("100.00"),
            occupied_weight_kg=Decimal("1.000"),
        )],
    )

    assert result.status == "CANDIDATES_FOUND"
    assert result.candidates[0]["required_volume_cm3"] == 250
    assert result.candidates[0]["required_weight_kg"] == 1.25
    assert result.candidates[0]["distance_to_picking_m"] == 2



def test_physical_slotting_does_not_assume_missing_occupancy_is_zero():
    unknown = location("UNKNOWN", 1)
    unknown.pop("occupied_volume_cm3")
    unknown.pop("occupied_weight_kg")

    result = recommend_physical_slot(
        product_id=7,
        required_quantity=1,
        product_profile=profile(),
        locations=[unknown],
    )

    assert result.status == "NO_COMPATIBLE_LOCATION"
    assert result.candidates == ()
    assert result.rejected_locations[0]["reason"] == "UNKNOWN_CURRENT_OCCUPANCY"
