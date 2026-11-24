from app.workforce_planner import build_capacity_aware_assignment_plan


def test_planner_respects_shift_capacity_and_existing_workload():
    employees = [
        {"id": 1, "on_shift": True, "available": True, "remaining_capacity_minutes": 45},
        {"id": 2, "on_shift": True, "available": True, "remaining_capacity_minutes": 60},
    ]
    existing = [{"assigned_user_id": 2, "estimated_duration_minutes": 30}]
    pending = [
        {"id": 10, "priority": "URGENT", "estimated_duration_minutes": 40},
        {"id": 11, "priority": "NORMAL", "estimated_duration_minutes": 20},
        {"id": 12, "priority": "LOW", "estimated_duration_minutes": 10},
    ]

    plan = build_capacity_aware_assignment_plan(employees, existing, pending)

    assert plan == [
        {"task_id": 10, "assigned_user_id": 1},
        {"task_id": 11, "assigned_user_id": 2},
    ]


def test_planner_requires_shift_and_respects_unavailability():
    employees = [
        {"id": 1, "on_shift": False, "available": True, "remaining_capacity_minutes": 120},
        {"id": 2, "on_shift": True, "available": False, "remaining_capacity_minutes": 120},
    ]
    assert build_capacity_aware_assignment_plan(
        employees, [], [{"id": 1, "estimated_duration_minutes": 10}],
    ) == []


def test_planner_requires_competency_when_task_declares_one():
    employees = [
        {"id": 1, "on_shift": True, "available": True, "remaining_capacity_minutes": 120,
         "skills": [{"skill_code": "CASHIER", "level": 3}]},
        {"id": 2, "on_shift": True, "available": True, "remaining_capacity_minutes": 120,
         "skills": [{"skill_code": "FORKLIFT", "level": 2}]},
    ]
    plan = build_capacity_aware_assignment_plan(
        employees, [],
        [{"id": 1, "estimated_duration_minutes": 30, "required_skill_code": "forklift"}],
    )
    assert plan == [{"task_id": 1, "assigned_user_id": 2}]


def test_planner_does_not_overbook_capacity_and_keeps_priority_order():
    employees = [
        {"id": 5, "on_shift": True, "available": True, "remaining_capacity_minutes": 25},
    ]
    plan = build_capacity_aware_assignment_plan(
        employees, [],
        [
            {"id": 1, "priority": "NORMAL", "estimated_duration_minutes": 20},
            {"id": 2, "priority": "URGENT", "estimated_duration_minutes": 15},
        ],
    )
    assert plan == [{"task_id": 2, "assigned_user_id": 5}]
