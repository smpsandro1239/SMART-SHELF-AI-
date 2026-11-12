"""Descriptive workload metrics; deliberately not an employee availability model."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import fmean
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class WorkloadSummary:
    employees: tuple[dict[str, Any], ...]
    unassigned_active_tasks: int
    completed_tasks_with_duration: int
    average_completion_minutes: float | None


def summarize_workload(
    employees: Iterable[Mapping[str, Any]],
    tasks: Iterable[Mapping[str, Any]],
) -> WorkloadSummary:
    """Count recorded active tasks and calculate durations for valid completed tasks."""
    employee_rows = {
        int(user["id"]): {
            "user_id": int(user["id"]),
            "name": str(user["name"]),
            "active_task_count": 0,
            "in_progress_task_count": 0,
            "assigned_task_count": 0,
        }
        for user in employees
    }
    unassigned = 0
    durations: list[float] = []

    for task in tasks:
        status = str(task.get("status") or "")
        user_id = task.get("assigned_user_id")
        if status in {"PENDING", "ASSIGNED", "IN_PROGRESS"}:
            if user_id is None or int(user_id) not in employee_rows:
                unassigned += 1
            else:
                row = employee_rows[int(user_id)]
                row["active_task_count"] += 1
                if status == "IN_PROGRESS":
                    row["in_progress_task_count"] += 1
                elif status == "ASSIGNED":
                    row["assigned_task_count"] += 1

        if status == "COMPLETED":
            started = task.get("started_at")
            completed = task.get("completed_at")
            if isinstance(started, datetime) and isinstance(completed, datetime):
                seconds = (completed - started).total_seconds()
                if 0 <= seconds <= 7 * 24 * 60 * 60:
                    durations.append(seconds / 60.0)

    rows = tuple(sorted(
        employee_rows.values(),
        key=lambda row: (-row["active_task_count"], row["name"].casefold(), row["user_id"]),
    ))
    return WorkloadSummary(
        employees=rows,
        unassigned_active_tasks=unassigned,
        completed_tasks_with_duration=len(durations),
        average_completion_minutes=round(fmean(durations), 2) if durations else None,
    )
