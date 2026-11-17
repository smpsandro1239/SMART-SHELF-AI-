import pytest

from app.replenishment_policy import (
    PurchaseReorderInput,
    ShelfRefillInput,
    suggest_purchase_reorder,
    suggest_shelf_refill,
)


def shelf(**overrides):
    values = {
        "shelf_quantity": 2,
        "target_quantity": 12,
        "min_display_quantity": 3,
        "backroom_available_quantity": 20,
        "observation_confidence": 0.91,
        "observation_age_minutes": 2,
    }
    values.update(overrides)
    return ShelfRefillInput(**values)


def purchase(**overrides):
    values = {
        "on_hand_quantity": 8,
        "reserved_quantity": 1,
        "incoming_quantity": 2,
        "demand_until_receipt": 5,
        "reorder_point": 6,
        "target_max_quantity": 24,
        "minimum_order_quantity": 6,
        "pack_multiple": 6,
    }
    values.update(overrides)
    return PurchaseReorderInput(**values)


def test_shelf_refill_calculates_gap_and_caps_to_available_backroom_stock():
    result = suggest_shelf_refill(shelf())

    assert result.status == "NEEDS_REPLENISHMENT"
    assert result.shelf_gap_quantity == 10
    assert result.suggested_quantity == 10
    assert result.remaining_gap_quantity == 0
    assert result.requires_human_review is True


def test_shelf_refill_is_partial_when_backroom_stock_is_insufficient():
    result = suggest_shelf_refill(shelf(backroom_available_quantity=4))

    assert result.status == "NEEDS_REPLENISHMENT"
    assert result.suggested_quantity == 4
    assert result.remaining_gap_quantity == 6


def test_stale_observation_never_generates_quantity():
    result = suggest_shelf_refill(shelf(observation_age_minutes=16))

    assert result.status == "STALE_OBSERVATION"
    assert result.suggested_quantity is None
    assert result.requires_human_review is True


def test_low_confidence_never_generates_quantity():
    result = suggest_shelf_refill(shelf(observation_confidence=0.4))

    assert result.status == "LOW_CONFIDENCE"
    assert result.suggested_quantity is None


def test_missing_inventory_is_not_treated_as_zero_or_infinite():
    result = suggest_shelf_refill(shelf(backroom_available_quantity=None))

    assert result.status == "INVENTORY_UNKNOWN"
    assert result.suggested_quantity is None


def test_zero_backroom_stock_blocks_shelf_refill():
    result = suggest_shelf_refill(shelf(backroom_available_quantity=0))

    assert result.status == "BACKROOM_OUT_OF_STOCK"
    assert result.suggested_quantity == 0


def test_shelf_above_minimum_display_threshold_does_not_trigger():
    result = suggest_shelf_refill(shelf(shelf_quantity=4))

    assert result.status == "NO_ACTION"
    assert result.suggested_quantity == 0


def test_purchase_reorder_uses_projected_stock_and_rounds_to_pack_multiple():
    result = suggest_purchase_reorder(purchase())

    # 8 on hand + 2 incoming - 1 reserved - 5 demand = 4 projected.
    # Target 24 requires 20; supplier sells packs of 6, so order 24.
    assert result.status == "ORDER_RECOMMENDED"
    assert result.projected_stock_at_receipt == 4
    assert result.suggested_order_quantity == 24
    assert result.quantity_after_order == 28


def test_purchase_reorder_does_not_order_when_projected_stock_is_at_reorder_point():
    result = suggest_purchase_reorder(purchase(on_hand_quantity=10, demand_until_receipt=5))

    assert result.status == "NO_ORDER"
    assert result.suggested_order_quantity == 0


def test_purchase_reorder_respects_minimum_order_quantity():
    result = suggest_purchase_reorder(purchase(
        on_hand_quantity=6, reserved_quantity=0, incoming_quantity=0,
        demand_until_receipt=0, reorder_point=7, target_max_quantity=8,
        minimum_order_quantity=12, pack_multiple=6,
    ))

    assert result.suggested_order_quantity == 12


@pytest.mark.parametrize(
    "overrides",
    [
        {"shelf_quantity": -1},
        {"target_quantity": 0},
        {"min_display_quantity": 13},
        {"observation_confidence": 1.5},
        {"observation_age_minutes": float("nan")},
    ],
)
def test_shelf_refill_rejects_invalid_inputs(overrides):
    with pytest.raises(ValueError):
        suggest_shelf_refill(shelf(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"on_hand_quantity": -1},
        {"reserved_quantity": 9},
        {"target_max_quantity": 6, "reorder_point": 6},
        {"pack_multiple": 0},
    ],
)
def test_purchase_reorder_rejects_invalid_inputs(overrides):
    with pytest.raises(ValueError):
        suggest_purchase_reorder(purchase(**overrides))
