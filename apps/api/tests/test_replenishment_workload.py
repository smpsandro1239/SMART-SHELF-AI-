from datetime import datetime, timedelta, timezone

from app.replenishment_workload import summarize_workload


def test_workload_counts_active_tasks_per_employee_and_unassigned():
    result = summarize_workload(
        [{"id": 1, "name": "Ana"}, {"id": 2, "name": "Bruno"}],
        [
            {"assigned_user_id": 1, "status": "ASSIGNED"},
            {"assigned_user_id": 1, "status": "IN_PROGRESS"},
            {"assigned_user_id": None, "status": "PENDING"},
            {"assigned_user_id": 99, "status": "ASSIGNED"},
            {"assigned_user_id": 2, "status": "COMPLETED"},
        ],
    )

    assert result.employees[0]["user_id"] == 1
    assert result.employees[0]["active_task_count"] == 2
    assert result.employees[0]["in_progress_task_count"] == 1
    assert result.employees[1]["active_task_count"] == 0
    assert result.unassigned_active_tasks == 2


def test_workload_averages_only_valid_completed_durations():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = summarize_workload(
        [{"id": 1, "name": "Ana"}],
        [
            {"status": "COMPLETED", "started_at": start, "completed_at": start + timedelta(minutes=10)},
            {"status": "COMPLETED", "started_at": start, "completed_at": start + timedelta(minutes=30)},
            {"status": "COMPLETED", "started_at": None, "completed_at": start},
            {"status": "COMPLETED", "started_at": start, "completed_at": start - timedelta(minutes=1)},
            {"status": "IN_PROGRESS", "started_at": start, "completed_at": None},
        ],
    )

    assert result.completed_tasks_with_duration == 2
    assert result.average_completion_minutes == 20.0


def test_workload_returns_none_when_there_are_no_valid_durations():
    result = summarize_workload([], [])
    assert result.average_completion_minutes is None
    assert result.completed_tasks_with_duration == 0



def test_duration_benchmarks_are_grouped_and_hidden_below_five_samples():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tasks = [
        {
            "status": "COMPLETED",
            "started_at": start,
            "completed_at": start + timedelta(minutes=10 + index),
            "zone_name": "Bebidas",
            "priority": "HIGH",
        }
        for index in range(5)
    ]
    tasks.append({
        "status": "COMPLETED",
        "started_at": start,
        "completed_at": start + timedelta(minutes=20),
        "zone_name": "Frio",
        "priority": "LOW",
    })

    result = summarize_workload([{"id": 1, "name": "Ana"}], tasks)

    by_zone = {row["group"]: row for row in result.duration_by_zone}
    by_priority = {row["group"]: row for row in result.duration_by_priority}
    assert by_zone["Bebidas"]["status"] == "READY"
    assert by_zone["Bebidas"]["sample_count"] == 5
    assert by_zone["Frio"]["status"] == "INSUFFICIENT_SAMPLE"
    assert by_zone["Frio"]["average_completion_minutes"] is None
    assert by_priority["HIGH"]["average_completion_minutes"] == 12.0
    assert by_priority["LOW"]["status"] == "INSUFFICIENT_SAMPLE"
