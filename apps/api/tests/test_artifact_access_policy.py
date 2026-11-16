from datetime import datetime, timedelta, timezone

import pytest

from app.artifact_access_policy import evaluate_artifact_access


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def approved_kwargs():
    return {
        "artifact_reference_id": 12,
        "expected_artifact_type": "CROP",
        "expected_external_reference": "bucket/crops/12.jpg",
        "expected_sha256": "a" * 64,
        "source_retention_status": "ACTIVE",
        "source_legal_hold": False,
        "integration_status": "ACTIVE",
        "inventory_complete": True,
        "inventory_integrity_verified": True,
        "inventory_generated_at": NOW - timedelta(minutes=2),
        "inventory_verified_at": NOW - timedelta(minutes=1),
        "inventory_max_age_seconds": 900,
        "inventory_entry": {
            "artifact_type": "CROP",
            "external_reference": "bucket/crops/12.jpg",
            "sha256": "a" * 64,
            "state": "PRESENT",
        },
        "latest_disposition_event": None,
        "latest_disposition_at": None,
        "now": NOW,
    }


def test_fresh_complete_present_artifact_is_approved():
    decision = evaluate_artifact_access(**approved_kwargs())
    assert decision.allowed is True
    assert decision.status == "APPROVED"
    assert decision.reasons == ()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("source_retention_status", "RESTRICTED", "source_image_not_active"),
        ("source_retention_status", "PURGED", "source_image_not_active"),
        ("source_legal_hold", True, "source_image_under_legal_hold"),
        ("integration_status", "REVOKED", "external_integration_not_active"),
        ("inventory_complete", False, "inventory_not_complete"),
        ("inventory_entry", None, "artifact_missing_from_inventory"),
        ("latest_disposition_event", "PROPOSED", "artifact_disposition_pending_or_approved"),
        ("latest_disposition_event", "APPROVED", "artifact_disposition_pending_or_approved"),
        ("latest_disposition_event", "DISPOSAL_ATTESTED", "artifact_disposal_attested"),
    ],
)
def test_restrictions_fail_closed(field, value, reason):
    kwargs = approved_kwargs()
    kwargs[field] = value
    decision = evaluate_artifact_access(**kwargs)
    assert decision.allowed is False
    assert reason in decision.reasons


def test_absent_inventory_entry_is_not_consumable():
    kwargs = approved_kwargs()
    kwargs["inventory_entry"] = {"state": "ABSENT"}
    decision = evaluate_artifact_access(**kwargs)
    assert "artifact_not_present" in decision.reasons


def test_stale_inventory_is_not_consumable():
    kwargs = approved_kwargs()
    kwargs["inventory_generated_at"] = NOW - timedelta(hours=2)
    decision = evaluate_artifact_access(**kwargs)
    assert "inventory_stale" in decision.reasons


def test_inventory_must_postdate_disposition():
    kwargs = approved_kwargs()
    kwargs["latest_disposition_event"] = "REJECTED"
    kwargs["latest_disposition_at"] = NOW - timedelta(minutes=1)
    kwargs["inventory_generated_at"] = NOW - timedelta(minutes=2)
    decision = evaluate_artifact_access(**kwargs)
    assert "inventory_predates_disposition" in decision.reasons


def test_unknown_disposition_state_is_blocked():
    kwargs = approved_kwargs()
    kwargs["latest_disposition_event"] = "UNRECOGNIZED"
    decision = evaluate_artifact_access(**kwargs)
    assert "artifact_disposition_state_unknown" in decision.reasons


def test_naive_timestamps_are_rejected():
    kwargs = approved_kwargs()
    kwargs["inventory_generated_at"] = datetime(2026, 11, 16, 11, 58)
    with pytest.raises(ValueError, match="timezone"):
        evaluate_artifact_access(**kwargs)


@pytest.mark.parametrize(
    ("artifact_id", "max_age"),
    [(0, 900), (12, 0), (12, -1)],
)
def test_invalid_policy_parameters_are_rejected(artifact_id, max_age):
    kwargs = approved_kwargs()
    kwargs["artifact_reference_id"] = artifact_id
    kwargs["inventory_max_age_seconds"] = max_age
    with pytest.raises(ValueError):
        evaluate_artifact_access(**kwargs)

@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("artifact_type", "inventory_artifact_type_mismatch"),
        ("external_reference", "inventory_external_reference_mismatch"),
        ("sha256", "inventory_artifact_sha256_mismatch"),
    ],
)
def test_inventory_must_match_exact_declared_artifact(field, reason):
    kwargs = approved_kwargs()
    kwargs["inventory_entry"][field] = "different-value"
    decision = evaluate_artifact_access(**kwargs)
    assert decision.allowed is False
    assert reason in decision.reasons


def test_inventory_timestamp_equal_to_disposition_is_not_current():
    kwargs = approved_kwargs()
    kwargs["latest_disposition_event"] = "REJECTED"
    kwargs["latest_disposition_at"] = NOW - timedelta(minutes=2)
    kwargs["inventory_generated_at"] = NOW - timedelta(minutes=2)
    decision = evaluate_artifact_access(**kwargs)
    assert decision.allowed is False
    assert "inventory_predates_disposition" in decision.reasons


def test_unverified_inventory_integrity_blocks_access():
    kwargs = approved_kwargs()
    kwargs["inventory_integrity_verified"] = False
    decision = evaluate_artifact_access(**kwargs)
    assert decision.allowed is False
    assert "inventory_integrity_unverified" in decision.reasons


@pytest.mark.parametrize(
    ("sha256", "expected_reason"),
    [
        (None, "artifact_sha256_not_declared"),
        ("", "artifact_sha256_not_declared"),
        ("not-a-hash", "artifact_sha256_missing_or_invalid"),
        ("a" * 63, "artifact_sha256_missing_or_invalid"),
        ("g" * 64, "artifact_sha256_missing_or_invalid"),
    ],
)
def test_artifact_without_valid_sha256_is_never_approved(sha256, expected_reason):
    kwargs = approved_kwargs()
    kwargs["expected_sha256"] = sha256
    kwargs["inventory_entry"]["sha256"] = sha256

    decision = evaluate_artifact_access(**kwargs)

    assert decision.allowed is False
    assert expected_reason in decision.reasons

def test_inventory_verification_cannot_precede_generation():
    kwargs = approved_kwargs()
    kwargs["inventory_generated_at"] = NOW - timedelta(minutes=1)
    kwargs["inventory_verified_at"] = NOW - timedelta(minutes=2)

    decision = evaluate_artifact_access(**kwargs)

    assert decision.allowed is False
    assert "inventory_verification_precedes_generation" in decision.reasons

@pytest.mark.parametrize(
    ("future_seconds", "blocked"),
    [(120, False), (121, True)],
)
def test_inventory_verification_clock_skew_uses_two_minute_boundary(
    future_seconds, blocked
):
    kwargs = approved_kwargs()
    kwargs["inventory_generated_at"] = NOW - timedelta(minutes=5)
    kwargs["inventory_verified_at"] = NOW + timedelta(seconds=future_seconds)

    decision = evaluate_artifact_access(**kwargs)

    assert ("inventory_timestamp_in_future" in decision.reasons) is blocked
    assert decision.allowed is (not blocked)


@pytest.mark.parametrize(
    ("field", "future_seconds"),
    [
        ("inventory_generated_at", 121),
        ("inventory_verified_at", 121),
    ],
)
def test_each_inventory_timestamp_is_independently_checked_for_future_skew(
    field, future_seconds
):
    kwargs = approved_kwargs()
    kwargs[field] = NOW + timedelta(seconds=future_seconds)

    decision = evaluate_artifact_access(**kwargs)

    assert decision.allowed is False
    assert "inventory_timestamp_in_future" in decision.reasons

