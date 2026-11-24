from app.replenishment_assignment import build_balanced_assignment_plan


def test_assignment_plan_balances_existing_workload_and_prefers_zone_continuity():
    employees = [
        {"id": 10, "active": True},
        {"id": 20, "active": True},
        {"id": 30, "active": True},
    ]
    existing = [
        {"id": 1, "assigned_user_id": 10, "zone_name": "A"},
        {"id": 2, "assigned_user_id": 10, "zone_name": "A"},
        {"id": 3, "assigned_user_id": 20, "zone_name": "B"},
    ]
    pending = [
        {"id": 8, "priority": "NORMAL", "zone_name": "A"},
        {"id": 9, "priority": "URGENT", "zone_name": "B"},
    ]

    plan = build_balanced_assignment_plan(employees, existing, pending)

    assert plan == [
        {"task_id": 9, "assigned_user_id": 30},
        {"task_id": 8, "assigned_user_id": 20},
    ]


def test_assignment_plan_uses_priority_then_stable_task_order():
    employees = [{"id": 2}, {"id": 1}]
    tasks = [
        {"id": 30, "priority": "LOW"},
        {"id": 20, "priority": "URGENT"},
        {"id": 10, "priority": "HIGH"},
    ]

    plan = build_balanced_assignment_plan(employees, [], tasks)

    assert [item["task_id"] for item in plan] == [20, 10, 30]
    assert [item["assigned_user_id"] for item in plan] == [1, 2, 1]


def test_assignment_plan_is_empty_without_eligible_employees_or_tasks():
    assert build_balanced_assignment_plan([], [], [{"id": 1}]) == []
    assert build_balanced_assignment_plan([{"id": 1, "active": False}], [], [{"id": 1}]) == []
    assert build_balanced_assignment_plan([{"id": 1}], [], []) == []
