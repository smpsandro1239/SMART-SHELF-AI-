from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.edge_event_contract import (
    EdgeEventContractError,
    EdgeEventEnvelope,
    EdgeSequenceDisposition,
    classify_sequence,
    event_fingerprint,
    event_idempotency_key,
    verify_idempotent_replay,
)


def make_event(**overrides):
    values = {
        "schema_version": 1,
        "event_id": uuid4(),
        "event_type": "DEVICE_HEARTBEAT",
        "device_id": "edge-gateway-01",
        "store_id": 12,
        "shelf_id": None,
        "sequence_number": 1,
        "occurred_at": datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc),
        "payload": {"firmware_version": "1.4.2", "battery_pct": 87.5, "network_status": "ONLINE"},
    }
    values.update(overrides)
    return EdgeEventEnvelope(**values)


def test_heartbeat_event_accepts_timezone_aware_tenant_bound_envelope():
    event = make_event()

    assert event.store_id == 12
    assert event.device_id == "edge-gateway-01"
    assert event.event_type == "DEVICE_HEARTBEAT"


def test_shelf_capture_requires_hash_dimensions_and_supported_media_type():
    event = make_event(
        event_type="SHELF_CAPTURED",
        shelf_id=44,
        payload={
            "capture_id": str(uuid4()),
            "image_sha256": "a" * 64,
            "width": 1920,
            "height": 1080,
            "media_type": "image/jpeg",
        },
    )

    assert event.shelf_id == 44


def test_shelf_observation_is_evidence_only_and_uses_normalized_bounding_boxes():
    event = make_event(
        event_type="SHELF_OBSERVATION",
        shelf_id=44,
        payload={
            "capture_id": str(uuid4()),
            "model_version": "detector@sha256",
            "observations": [
                {"label": "product", "confidence": 0.96, "bbox": [0.1, 0.2, 0.4, 0.8]}
            ],
        },
    )

    assert event.payload["observations"][0]["confidence"] == 0.96
    assert "stock_quantity" not in event.payload


def test_task_acknowledgement_requires_positive_task_and_version():
    event = make_event(
        event_type="TASK_ACKNOWLEDGED",
        payload={"task_id": 101, "task_version": 3, "action": "STARTED"},
    )

    assert event.payload["task_version"] == 3


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"store_id": 0}, "greater than 0"),
        ({"device_id": "bad device"}, "safe ASCII"),
        ({"occurred_at": datetime(2026, 11, 21, 12, 0)}, "explicit timezone"),
        ({"event_type": "UNKNOWN"}, "event_type"),
        ({"event_type": "DEVICE_HEARTBEAT", "shelf_id": 44}, "must not reference a shelf"),
        ({"payload": {"battery_pct": float("nan")}}, "finite"),
        ({"payload": {"battery_pct": 101}}, "between 0 and 100"),
        ({"payload": {"firmware_version": 12}}, "firmware_version"),
        ({"payload": {"network_status": "MAYBE"}}, "network_status"),
    ],
)
def test_invalid_edge_event_envelopes_are_rejected(overrides, message):
    with pytest.raises(ValidationError, match=message):
        make_event(**overrides)


def test_shelf_capture_rejects_invalid_hash_and_unbounded_dimensions():
    base = {
        "capture_id": str(uuid4()),
        "image_sha256": "A" * 64,
        "width": 1920,
        "height": 1080,
        "media_type": "image/jpeg",
    }
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        make_event(event_type="SHELF_CAPTURED", shelf_id=44, payload=base)
    with pytest.raises(ValidationError, match="width"):
        make_event(
            event_type="SHELF_CAPTURED",
            shelf_id=44,
            payload={**base, "image_sha256": "a" * 64, "width": 0},
        )


def test_shelf_observation_rejects_invalid_bbox_and_does_not_accept_extra_fields():
    payload = {
        "capture_id": str(uuid4()),
        "model_version": "model-v1",
        "observations": [
            {"label": "product", "confidence": 0.9, "bbox": [0.4, 0.2, 0.1, 0.8]}
        ],
    }
    with pytest.raises(ValidationError, match="bbox"):
        make_event(event_type="SHELF_OBSERVATION", shelf_id=44, payload=payload)
    with pytest.raises(ValidationError, match="exactly label"):
        make_event(
            event_type="SHELF_OBSERVATION",
            shelf_id=44,
            payload={
                **payload,
                "observations": [{"label": "product", "confidence": 0.9, "bbox": [0, 0, 1, 1], "sku_id": 7}],
            },
        )


def test_payload_is_bounded_and_rejects_non_json_objects():
    with pytest.raises(ValidationError, match="JSON-compatible"):
        make_event(payload={"bad": object()})
    with pytest.raises(ValidationError, match="64 KiB"):
        make_event(payload={"blob": "x" * 70000})


def test_event_fingerprint_is_stable_and_sensitive_to_content():
    event = make_event()
    same = EdgeEventEnvelope.model_validate(event.model_dump())
    changed = make_event(event_id=event.event_id, payload={"firmware_version": "1.4.3"})

    assert event_fingerprint(event) == event_fingerprint(same)
    assert event_fingerprint(event) != event_fingerprint(changed)


def test_idempotency_key_is_device_scoped_and_within_database_column_limit():
    event = make_event()
    key = event_idempotency_key(event)

    assert key.startswith("edge:")
    assert str(event.event_id) in key
    assert len(key) <= 160


def test_exact_replay_is_idempotent_but_reused_event_id_with_changed_payload_conflicts():
    event = make_event()
    same = EdgeEventEnvelope.model_validate(event.model_dump())
    changed = make_event(event_id=event.event_id, payload={"firmware_version": "changed"})

    assert verify_idempotent_replay(event_fingerprint(event), event_fingerprint(same)) is True
    with pytest.raises(EdgeEventContractError, match="reused with different content"):
        verify_idempotent_replay(event_fingerprint(event), event_fingerprint(changed))


@pytest.mark.parametrize(
    "last,incoming,expected",
    [
        (0, 1, EdgeSequenceDisposition.NEXT),
        (10, 11, EdgeSequenceDisposition.NEXT),
        (10, 14, EdgeSequenceDisposition.GAP),
        (10, 10, EdgeSequenceDisposition.STALE),
        (10, 7, EdgeSequenceDisposition.STALE),
    ],
)
def test_device_sequence_classification_is_deterministic_without_mutating_cursor(last, incoming, expected):
    assert classify_sequence(last, incoming) is expected


def test_sequence_classification_rejects_boolean_and_negative_values():
    with pytest.raises(EdgeEventContractError):
        classify_sequence(True, 1)
    with pytest.raises(EdgeEventContractError):
        classify_sequence(0, False)
    with pytest.raises(EdgeEventContractError):
        classify_sequence(-1, 1)
