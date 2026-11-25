"""Capacity-aware assignment planning using persisted workforce constraints."""

from collections import Counter
from typing import Any


_PRIORITY_ORDER = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}


def build_capacity_aware_assignment_plan(
    employees: list[dict[str, Any]],
    existing_tasks: list[dict[str, Any]],
    pending_tasks: list[dict[str, Any]],
) -> list[dict[str, int]]:
    """Allocate tasks only to on-shift, available and skilled employees with spare minutes."""
    eligible = {
        int(employee["id"]): employee
        for employee in employees
        if employee.get("active", True)
        and employee.get("on_shift", False)
        and employee.get("available", False)
        and int(employee.get("remaining_capacity_minutes", 0)) > 0
    }
    if not eligible or not pending_tasks:
        return []

    remaining = {
        employee_id: max(0, int(employee.get("remaining_capacity_minutes", 0)))
        for employee_id, employee in eligible.items()
    }
    zone_loads: dict[int, Counter[str]] = {
        employee_id: Counter() for employee_id in eligible
    }
    for task in existing_tasks:
        assignee = task.get("assigned_user_id")
        if assignee is None or int(assignee) not in eligible:
            continue
        employee_id = int(assignee)
        duration = max(1, int(task.get("estimated_duration_minutes", 15)))
        remaining[employee_id] = max(0, remaining[employee_id] - duration)
        zone = task.get("zone_name")
        if zone:
            zone_loads[employee_id][str(zone)] += 1

    pending = sorted(
        pending_tasks,
        key=lambda task: (
            _PRIORITY_ORDER.get(str(task.get("priority", "NORMAL")).upper(), 2),
            int(task.get("id", 0)),
        ),
    )
    plan: list[dict[str, int]] = []
    for task in pending:
        duration = max(1, int(task.get("estimated_duration_minutes", 15)))
        required_skill = str(task.get("required_skill_code") or "").strip().upper()
        zone = str(task.get("zone_name") or "")
        candidates = []
        for employee_id, employee in eligible.items():
            skills = {
                str(skill.get("skill_code", "")).upper(): int(skill.get("level", 1))
                for skill in employee.get("skills", [])
            }
            if required_skill and skills.get(required_skill, 0) < 1:
                continue
            if remaining[employee_id] < duration:
                continue
            candidates.append(employee_id)
        if not candidates:
            continue
        employee_id = min(
            candidates,
            key=lambda candidate: (
                -remaining[candidate],
                -zone_loads[candidate][zone] if zone else 0,
                candidate,
            ),
        )
        plan.append({"task_id": int(task["id"]), "assigned_user_id": employee_id})
        remaining[employee_id] -= duration
        if zone:
            zone_loads[employee_id][zone] += 1
    return plan
