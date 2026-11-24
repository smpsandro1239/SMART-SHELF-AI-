"""Deterministic workload-aware assignment planning for replenishment tasks.

The planner proposes assignments only. Callers remain responsible for authorization,
locking and persisting the resulting task transitions.
"""

from collections import Counter
from typing import Any


_PRIORITY_ORDER = {"URGENT": 0, "HIGH": 1, "NORMAL": 2, "LOW": 3}


def build_balanced_assignment_plan(
    employees: list[dict[str, Any]],
    existing_tasks: list[dict[str, Any]],
    pending_tasks: list[dict[str, Any]],
) -> list[dict[str, int]]:
    """Assign pending tasks to the least-loaded employee, preferring zone continuity.

    Existing active workload is counted before planning. Within equal workload,
    an employee already working in the task's zone is preferred; stable employee
    IDs make the result deterministic across runs.
    """
    eligible = sorted(
        (employee for employee in employees if employee.get("active", True)),
        key=lambda employee: int(employee["id"]),
    )
    if not eligible or not pending_tasks:
        return []

    loads: Counter[int] = Counter()
    zone_loads: dict[int, Counter[str]] = {
        int(employee["id"]): Counter() for employee in eligible
    }

    for task in existing_tasks:
        assignee = task.get("assigned_user_id")
        if assignee is None or int(assignee) not in zone_loads:
            continue
        employee_id = int(assignee)
        loads[employee_id] += 1
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
        zone = str(task.get("zone_name") or "")
        employee_id = min(
            (int(employee["id"]) for employee in eligible),
            key=lambda candidate: (
                loads[candidate],
                -zone_loads[candidate][zone] if zone else 0,
                candidate,
            ),
        )
        plan.append({"task_id": int(task["id"]), "assigned_user_id": employee_id})
        loads[employee_id] += 1
        if zone:
            zone_loads[employee_id][zone] += 1

    return plan
