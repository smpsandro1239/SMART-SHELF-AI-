from datetime import datetime, timezone, timedelta

import pytest

from app.operational_decision_engine import DecisionPolicy, evaluate_shelf_decision


NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def test_fresh_low_stock_observation_recommends_review_but_not_stock_movement():
    result = evaluate_shelf_decision(
        now=NOW,
        observation={"status": "LOW_STOCK", "observed_at": NOW, "confidence": 0.91, "source": "camera"},
        inventory={"available_quantity": 4, "recorded_at": NOW},
        demand_forecast={"predicted_units": 8, "horizon_hours": 12, "generated_at": NOW},
    )

    assert result["status"] == "ACTION_RECOMMENDED"
    assert result["priority"] == "NORMAL"
    assert result["suggested_replenishment_quantity"] == 4
    assert result["requires_human_approval"] is True
    assert result["automatic_stock_movement_allowed"] is False
    assert {item["type"] for item in result["evidence"]} == {
        "SHELF_OBSERVATION", "INVENTORY_SNAPSHOT", "DEMAND_FORECAST"
    }


def test_stale_observation_does_not_trigger_visual_recommendation():
    result = evaluate_shelf_decision(
        now=NOW,
        observation={"status": "EMPTY", "observed_at": NOW - timedelta(hours=8),
                     "confidence": 0.99, "source": "mobile"},
        inventory=None,
    )

    assert result["status"] == "MONITOR"
    assert result["suggested_replenishment_quantity"] is None
    assert any("desatualizada" in warning for warning in result["warnings"])


def test_low_confidence_observation_does_not_trigger_recommendation():
    result = evaluate_shelf_decision(
        now=NOW,
        observation={"status": "EMPTY", "observed_at": NOW, "confidence": 0.2},
        inventory=None,
    )

    assert result["status"] == "MONITOR"
    assert any("confiança" in warning for warning in result["warnings"])


def test_active_task_suppresses_duplicate_recommendation():
    result = evaluate_shelf_decision(
        now=NOW,
        observation={"status": "EMPTY", "observed_at": NOW, "confidence": 0.99},
        inventory={"available_quantity": 0, "recorded_at": NOW},
        demand_forecast={"predicted_units": 5, "horizon_hours": 12, "generated_at": NOW},
        active_tasks=[{"id": 42, "status": "IN_PROGRESS"}],
    )

    assert result["status"] == "ALREADY_IN_PROGRESS"
    assert result["suggested_replenishment_quantity"] is None


def test_missing_inventory_never_becomes_zero_or_invented_quantity():
    result = evaluate_shelf_decision(
        now=NOW,
        observation={"status": "LOW_STOCK", "observed_at": NOW, "confidence": 0.9},
        inventory=None,
        demand_forecast={"predicted_units": 10, "horizon_hours": 12, "generated_at": NOW},
    )

    assert result["status"] == "ACTION_RECOMMENDED"
    assert result["suggested_replenishment_quantity"] is None
    assert any("falta inventário" in warning for warning in result["warnings"])


def test_forecast_must_be_recent_and_within_supported_horizon():
    result = evaluate_shelf_decision(
        now=NOW,
        observation=None,
        inventory={"available_quantity": 1, "recorded_at": NOW},
        demand_forecast={"predicted_units": 10, "horizon_hours": 24,
                         "generated_at": NOW - timedelta(days=2)},
    )

    assert result["status"] == "MONITOR"
    assert result["suggested_replenishment_quantity"] is None


@pytest.mark.parametrize("timestamp", ["2026-11-12T12:00:00", "not-a-date", None])
def test_timestamps_must_be_valid_and_timezone_aware(timestamp):
    with pytest.raises(ValueError):
        evaluate_shelf_decision(
            now=NOW,
            observation={"status": "EMPTY", "observed_at": timestamp, "confidence": 0.9},
            inventory=None,
        )


@pytest.mark.parametrize("quantity", [-1, float("nan"), float("inf"), True, "3"])
def test_inventory_quantity_rejects_invalid_values(quantity):
    with pytest.raises(ValueError):
        evaluate_shelf_decision(
            now=NOW, observation=None,
            inventory={"available_quantity": quantity, "recorded_at": NOW},
        )


def test_policy_rejects_boolean_age_limit():
    with pytest.raises(ValueError):
        evaluate_shelf_decision(
            now=NOW, observation=None, inventory=None,
            policy=DecisionPolicy(observation_max_age_minutes=True),
        )


def test_no_evidence_returns_insufficient_evidence():
    result = evaluate_shelf_decision(now=NOW, observation=None, inventory=None)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["priority"] == "NONE"


def test_future_dated_observation_is_not_trusted():
    result = evaluate_shelf_decision(
        now=NOW,
        observation={"status": "EMPTY", "observed_at": NOW + timedelta(minutes=5), "confidence": 0.99},
        inventory=None,
    )

    assert result["status"] == "MONITOR"
    assert any("timestamp no futuro" in warning for warning in result["warnings"])


def test_future_dated_inventory_and_forecast_are_not_used_for_quantity():
    result = evaluate_shelf_decision(
        now=NOW,
        observation={"status": "LOW_STOCK", "observed_at": NOW, "confidence": 0.9},
        inventory={"available_quantity": 1, "recorded_at": NOW + timedelta(minutes=1)},
        demand_forecast={"predicted_units": 10, "horizon_hours": 12,
                         "generated_at": NOW + timedelta(minutes=1)},
    )

    assert result["status"] == "ACTION_RECOMMENDED"
    assert result["suggested_replenishment_quantity"] is None
    assert any("timestamp no futuro" in warning for warning in result["warnings"])


def test_stock_coverage_threshold_prevents_early_replenishment_alert():
    result = evaluate_shelf_decision(
        now=NOW,
        observation=None,
        inventory={"available_quantity": 20, "recorded_at": NOW},
        demand_forecast={"predicted_units": 10, "horizon_hours": 24, "generated_at": NOW},
    )

    assert result["status"] == "MONITOR"
    assert result["inventory_coverage_hours"] == 48.0


def test_stock_coverage_is_reported_and_triggers_when_below_policy():
    result = evaluate_shelf_decision(
        now=NOW,
        observation=None,
        inventory={"available_quantity": 4, "recorded_at": NOW},
        demand_forecast={"predicted_units": 8, "horizon_hours": 12, "generated_at": NOW},
    )

    assert result["status"] == "ACTION_RECOMMENDED"
    assert result["inventory_coverage_hours"] == 6.0
