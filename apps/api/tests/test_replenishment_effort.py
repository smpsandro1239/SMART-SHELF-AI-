from datetime import datetime, timedelta, timezone

import pytest

from app.replenishment_effort import enrich_plan_with_effort_estimates


def _candidate(zone="Bebidas", priority="HIGH"):
    return {"zone_name": zone, "proposed_priority": priority, "product_id": 1}


def _history(count=5, zone="Bebidas", priority="HIGH", minutes=10):
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return [
        {
            "zone_name": zone,
            "priority": priority,
            "started_at": start + timedelta(days=index),
            "completed_at": start + timedelta(days=index, minutes=minutes + index),
        }
        for index in range(count)
    ]


def test_effort_estimate_uses_zone_and_priority_when_sample_is_sufficient():
    result = enrich_plan_with_effort_estimates(
        [_candidate()],
        _history(minutes=10),
    )

    item = result["recommendations"][0]
    assert item["effort_estimate_status"] == "ESTIMATED"
    assert item["effort_estimate_basis"] == "ZONE_AND_PRIORITY_HISTORY"
    assert item["effort_estimate_sample_count"] == 5
    assert item["estimated_elapsed_minutes"] == 12
    assert result["summary"]["estimated_total_elapsed_minutes"] == 12


def test_effort_estimate_falls_back_to_zone_only_history():
    history = _history(priority="NORMAL")
    result = enrich_plan_with_effort_estimates(
        [_candidate(priority="HIGH")],
        history,
    )

    item = result["recommendations"][0]
    assert item["effort_estimate_status"] == "ESTIMATED"
    assert item["effort_estimate_basis"] == "ZONE_HISTORY"
    assert item["estimated_elapsed_minutes"] == 12


def test_effort_estimate_is_unknown_below_minimum_sample():
    result = enrich_plan_with_effort_estimates(
        [_candidate()],
        _history(count=4),
    )

    item = result["recommendations"][0]
    assert item["effort_estimate_status"] == "UNKNOWN"
    assert item["estimated_elapsed_minutes"] is None
    assert result["summary"]["unestimated_candidates"] == 1


def test_effort_estimate_ignores_invalid_and_unbounded_durations():
    history = _history()
    history.extend([
        {"zone_name": "Bebidas", "priority": "HIGH", "started_at": None,
         "completed_at": datetime.now(timezone.utc)},
        {"zone_name": "Bebidas", "priority": "HIGH",
         "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
         "completed_at": datetime(2026, 1, 10, tzinfo=timezone.utc)},
    ])
    result = enrich_plan_with_effort_estimates([_candidate()], history)
    assert result["summary"]["historical_valid_samples"] == 5


def test_effort_estimate_does_not_mutate_candidate():
    candidate = _candidate()
    original = dict(candidate)
    enrich_plan_with_effort_estimates([candidate], _history())
    assert candidate == original


@pytest.mark.parametrize("minimum", [True, 1, 101, 2.5])
def test_effort_estimate_rejects_invalid_sample_threshold(minimum):
    with pytest.raises(ValueError):
        enrich_plan_with_effort_estimates([], [], minimum_sample_size=minimum)
