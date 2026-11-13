from datetime import datetime, timedelta, timezone

import pytest

from app.observation_consensus import evaluate_observation_consensus


NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


def rows(status="EMPTY", count=3, *, confidence=0.9, spacing=30):
    return [
        {
            "status": status,
            "observed_at": NOW - timedelta(seconds=spacing * (count - index - 1)),
            "confidence": confidence,
            "source": "camera-a",
        }
        for index in range(count)
    ]


def test_repeated_fresh_observations_reach_consensus():
    result = evaluate_observation_consensus(rows(), now=NOW)

    assert result["status"] == "CONFIRMED"
    assert result["consensus_observation_status"] == "EMPTY"
    assert result["confirmations"] == 3
    assert result["sources"] == ["camera-a"]
    assert result["automatic_task_creation_allowed"] is False
    assert result["automatic_stock_movement_allowed"] is False


def test_single_observation_does_not_trigger_consensus():
    result = evaluate_observation_consensus(rows(count=1), now=NOW)

    assert result["status"] == "NO_CONSENSUS"
    assert result["confirmations"] == 0


def test_frame_burst_is_not_counted_as_independent_confirmations():
    result = evaluate_observation_consensus(
        rows(count=5, spacing=1), now=NOW, minimum_interval_seconds=10
    )

    assert result["status"] == "NO_CONSENSUS"


def test_stale_future_and_low_confidence_observations_are_ignored():
    history = [
        *rows(count=2),
        {"status": "EMPTY", "observed_at": NOW - timedelta(hours=1), "confidence": 0.99},
        {"status": "EMPTY", "observed_at": NOW + timedelta(minutes=1), "confidence": 0.99},
        {"status": "EMPTY", "observed_at": NOW, "confidence": 0.2},
    ]
    result = evaluate_observation_consensus(history, now=NOW)

    assert result["status"] == "NO_CONSENSUS"
    assert result["ignored_observations"] == {
        "future": 1, "stale": 1, "low_confidence": 1, "irrelevant": 0
    }


def test_competing_confirmed_statuses_return_conflict():
    history = rows("EMPTY") + rows("MISPLACED")
    result = evaluate_observation_consensus(history, now=NOW)

    assert result["status"] == "CONFLICT"
    assert result["consensus_observation_status"] is None
    assert result["confirmations"] == 0


def test_clear_winner_can_be_selected_when_other_status_is_not_confirmed():
    history = rows("EMPTY") + rows("MISPLACED", count=2)
    result = evaluate_observation_consensus(history, now=NOW)

    assert result["status"] == "CONFIRMED"
    assert result["consensus_observation_status"] == "EMPTY"


@pytest.mark.parametrize("kwargs", [
    {"window_minutes": 0},
    {"minimum_confirmations": 1},
    {"minimum_interval_seconds": 0},
    {"minimum_interval_seconds": -1},
    {"minimum_confidence": 1.1},
    {"minimum_confidence": True},
])
def test_invalid_policy_is_rejected(kwargs):
    with pytest.raises(ValueError):
        evaluate_observation_consensus([], now=NOW, **kwargs)


def test_timezone_naive_timestamp_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_observation_consensus(
            [{"status": "EMPTY", "observed_at": datetime(2026, 11, 13, 12), "confidence": 0.9}],
            now=NOW,
        )


def test_non_finite_confidence_is_rejected():
    with pytest.raises(ValueError, match="confidence"):
        evaluate_observation_consensus(
            [{"status": "EMPTY", "observed_at": NOW, "confidence": float("nan")}],
            now=NOW,
        )
