import pytest

from app.replenishment_planning import build_replenishment_plan


def recommendation(shelf_id, status, **overrides):
    item = {
        "store_id": 1, "shelf_id": shelf_id, "shelf_code": f"S-{shelf_id}",
        "zone_id": 10, "zone_name": "Bebidas", "product_id": shelf_id,
        "product_name": f"Produto {shelf_id}", "recommendation_status": status,
        "suggested_quantity": 5 if status == "NEEDS_REPLENISHMENT" else None,
    }
    item.update(overrides)
    return item


def test_plan_prioritises_actionable_refill_and_marks_it_creatable():
    plan = build_replenishment_plan([
        recommendation(1, "LOW_CONFIDENCE"),
        recommendation(2, "NEEDS_REPLENISHMENT"),
        recommendation(3, "STALE_OBSERVATION"),
    ])

    items = [item for group in plan.groups for item in group.items]
    assert items[0]["shelf_id"] == 2
    assert items[0]["proposed_priority"] == "HIGH"
    assert items[0]["task_creation_allowed"] is True
    assert items[1]["task_creation_allowed"] is False


def test_plan_excludes_no_action_and_existing_active_tasks():
    plan = build_replenishment_plan([
        recommendation(1, "NO_ACTION"),
        recommendation(2, "NEEDS_REPLENISHMENT"),
    ], active_keys={(2, 2)})

    assert plan.total_candidates == 0
    assert plan.excluded == {"NO_ACTION": 1, "ACTIVE_TASK_EXISTS": 1}


def test_plan_groups_items_by_zone_and_applies_limit():
    plan = build_replenishment_plan([
        recommendation(1, "NEEDS_REPLENISHMENT", zone_id=2, zone_name="Frio"),
        recommendation(2, "NEEDS_REPLENISHMENT", zone_id=1, zone_name="Bebidas"),
        recommendation(3, "NEEDS_REPLENISHMENT", zone_id=1, zone_name="Bebidas"),
    ], limit=2)

    assert plan.returned_candidates == 2
    assert [group.zone_name for group in plan.groups] == ["Bebidas"]
    assert len(plan.groups[0].items) == 2


@pytest.mark.parametrize("limit", [0, 501, True, 1.5])
def test_plan_rejects_invalid_limit(limit):
    with pytest.raises(ValueError):
        build_replenishment_plan([], limit=limit)


def test_visual_status_without_numeric_quantity_never_allows_task_creation():
    plan = build_replenishment_plan([
        recommendation(1, "NEEDS_REPLENISHMENT", suggested_quantity=None),
    ])
    item = plan.groups[0].items[0]
    assert item["task_creation_allowed"] is False
    assert item["proposed_priority"] == "REVIEW"
