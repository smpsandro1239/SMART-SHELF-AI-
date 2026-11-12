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
