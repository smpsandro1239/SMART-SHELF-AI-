"""Versioned, tenant-bound event envelope for future Edge AI synchronization.

This module validates the wire contract only. It does not authenticate devices,
persist events, advance cursors, mutate inventory, or acknowledge delivery.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_PAYLOAD_BYTES = 64 * 1024
_MAX_JSON_DEPTH = 12
_MAX_COLLECTION_ITEMS = 1000


class EdgeEventContractError(ValueError):
    """Raised when an Edge AI event violates the versioned wire contract."""


class EdgeSequenceDisposition(str, Enum):
    NEXT = "NEXT"
    GAP = "GAP"
    STALE = "STALE"


class EdgeEventEnvelope(BaseModel):
    """Validated v1 event envelope; one event belongs to exactly one store/device."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1]
    event_id: UUID
    event_type: Literal[
        "DEVICE_HEARTBEAT",
        "SHELF_CAPTURED",
        "SHELF_OBSERVATION",
        "TASK_ACKNOWLEDGED",
    ]
    device_id: str
    store_id: int = Field(gt=0)
    shelf_id: int | None = Field(default=None, gt=0)
    sequence_number: int = Field(gt=0)
    occurred_at: datetime
    payload: dict[str, Any]

    @field_validator("device_id")
    @classmethod
    def validate_device_id(cls, value: str) -> str:
        if not _DEVICE_ID.fullmatch(value):
            raise ValueError("device_id must be 1-120 safe ASCII characters")
        return value

    @field_validator("occurred_at")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include an explicit timezone")
        return value

    @field_validator("payload")
    @classmethod
    def validate_bounded_json_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        def inspect(item: Any, depth: int = 0) -> None:
            if depth > _MAX_JSON_DEPTH:
                raise ValueError("payload nesting exceeds the maximum depth")
            if item is None or isinstance(item, (str, bool)):
                if isinstance(item, str) and len(item) > 4096:
                    raise ValueError("payload strings cannot exceed 4096 characters")
                return
            if isinstance(item, int):
                if not -(2**63) <= item <= (2**63 - 1):
                    raise ValueError("payload integers must fit signed 64-bit range")
                return
            if isinstance(item, float):
                if not math.isfinite(item):
                    raise ValueError("payload numbers must be finite")
                return
            if isinstance(item, list):
                if len(item) > _MAX_COLLECTION_ITEMS:
                    raise ValueError("payload arrays exceed the maximum item count")
                for child in item:
                    inspect(child, depth + 1)
                return
            if isinstance(item, dict):
                if len(item) > _MAX_COLLECTION_ITEMS:
                    raise ValueError("payload objects exceed the maximum item count")
                for key, child in item.items():
                    if not isinstance(key, str) or len(key) > 128:
                        raise ValueError("payload object keys must be strings of at most 128 characters")
                    inspect(child, depth + 1)
                return
            raise ValueError("payload must contain JSON-compatible values only")

        inspect(value)
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > _MAX_PAYLOAD_BYTES:
            raise ValueError("payload exceeds the 64 KiB limit")
        return value

    @model_validator(mode="after")
    def validate_event_specific_contract(self):
        payload = self.payload
        if self.event_type == "DEVICE_HEARTBEAT":
            if self.shelf_id is not None:
                raise ValueError("DEVICE_HEARTBEAT must not reference a shelf")
            allowed = {"firmware_version", "battery_pct", "network_status", "storage_free_bytes"}
            if not payload or set(payload) - allowed:
                raise ValueError("DEVICE_HEARTBEAT payload contains missing or unsupported fields")
            if "firmware_version" in payload and (
                not isinstance(payload["firmware_version"], str)
                or not payload["firmware_version"].strip()
            ):
                raise ValueError("firmware_version must be a non-empty string")
            if "network_status" in payload and (
                not isinstance(payload["network_status"], str)
                or payload["network_status"] not in {"ONLINE", "DEGRADED", "OFFLINE"}
            ):
                raise ValueError("network_status is unsupported")
            if "battery_pct" in payload and (
                isinstance(payload["battery_pct"], bool)
                or not isinstance(payload["battery_pct"], (int, float))
                or not 0 <= payload["battery_pct"] <= 100
                or (isinstance(payload["battery_pct"], float) and not math.isfinite(payload["battery_pct"]))
            ):
                raise ValueError("battery_pct must be a finite number between 0 and 100")
            if "storage_free_bytes" in payload and (
                type(payload["storage_free_bytes"]) is not int or payload["storage_free_bytes"] < 0
            ):
                raise ValueError("storage_free_bytes must be a non-negative integer")
        elif self.event_type == "SHELF_CAPTURED":
            if self.shelf_id is None:
                raise ValueError("SHELF_CAPTURED requires shelf_id")
            if set(payload) != {"capture_id", "image_sha256", "width", "height", "media_type"}:
                raise ValueError("SHELF_CAPTURED payload has missing or unsupported fields")
            if not isinstance(payload["capture_id"], str):
                raise ValueError("capture_id must be a UUID string")
            try:
                UUID(payload["capture_id"])
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("capture_id must be a UUID") from exc
            if not isinstance(payload["image_sha256"], str) or not _SHA256.fullmatch(payload["image_sha256"]):
                raise ValueError("image_sha256 must be lowercase SHA-256 hex")
            for dimension in ("width", "height"):
                if type(payload[dimension]) is not int or not 1 <= payload[dimension] <= 20000:
                    raise ValueError(f"{dimension} must be an integer between 1 and 20000")
            if not isinstance(payload["media_type"], str) or payload["media_type"] not in {"image/jpeg", "image/png", "image/webp"}:
                raise ValueError("media_type is not supported")
        elif self.event_type == "SHELF_OBSERVATION":
            if self.shelf_id is None:
                raise ValueError("SHELF_OBSERVATION requires shelf_id")
            if set(payload) != {"capture_id", "model_version", "observations"}:
                raise ValueError("SHELF_OBSERVATION payload has missing or unsupported fields")
            if not isinstance(payload["capture_id"], str):
                raise ValueError("capture_id must be a UUID string")
            try:
                UUID(payload["capture_id"])
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("capture_id must be a UUID") from exc
            if not isinstance(payload["model_version"], str) or not payload["model_version"].strip():
                raise ValueError("model_version must be a non-empty string")
            observations = payload["observations"]
            if not isinstance(observations, list) or len(observations) > _MAX_COLLECTION_ITEMS:
                raise ValueError("observations must be a bounded array")
            for observation in observations:
                if not isinstance(observation, dict) or set(observation) != {"label", "confidence", "bbox"}:
                    raise ValueError("each observation must contain exactly label, confidence and bbox")
                if not isinstance(observation["label"], str) or not observation["label"].strip():
                    raise ValueError("observation label must be non-empty")
                confidence = observation["confidence"]
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1 or (isinstance(confidence, float) and not math.isfinite(confidence)):
                    raise ValueError("observation confidence must be finite and between 0 and 1")
                bbox = observation["bbox"]
                if (
                    not isinstance(bbox, list)
                    or len(bbox) != 4
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, int) and not -(2**63) <= v <= 2**63 - 1) or (isinstance(v, float) and not math.isfinite(v)) for v in bbox)
                    or not (0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1)
                ):
                    raise ValueError("bbox must be normalized [x_min, y_min, x_max, y_max]")
        elif self.event_type == "TASK_ACKNOWLEDGED":
            if self.shelf_id is not None:
                raise ValueError("TASK_ACKNOWLEDGED must not reference a shelf")
            if set(payload) != {"task_id", "task_version", "action"}:
                raise ValueError("TASK_ACKNOWLEDGED payload has missing or unsupported fields")
            if type(payload["task_id"]) is not int or payload["task_id"] <= 0:
                raise ValueError("task_id must be a positive integer")
            if type(payload["task_version"]) is not int or payload["task_version"] <= 0:
                raise ValueError("task_version must be a positive integer")
            if not isinstance(payload["action"], str) or payload["action"] not in {"ACCEPTED", "STARTED", "COMPLETED"}:
                raise ValueError("task action is unsupported")
        return self


def canonical_event_bytes(event: EdgeEventEnvelope) -> bytes:
    """Return stable canonical JSON bytes for hashing, deduplication and audit."""
    return json.dumps(
        event.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def event_fingerprint(event: EdgeEventEnvelope) -> str:
    return hashlib.sha256(canonical_event_bytes(event)).hexdigest()


def event_idempotency_key(event: EdgeEventEnvelope) -> str:
    """Stable idempotency key scoped to the authenticated device identity."""
    device_scope = hashlib.sha256(event.device_id.encode("ascii")).hexdigest()
    return f"edge:{device_scope}:{event.event_id}"


def classify_sequence(last_accepted: int, incoming: int) -> EdgeSequenceDisposition:
    """Classify a device sequence without mutating its durable cursor."""
    if type(last_accepted) is not int or last_accepted < 0:
        raise EdgeEventContractError("last_accepted must be a non-negative integer")
    if type(incoming) is not int or incoming <= 0:
        raise EdgeEventContractError("incoming sequence must be a positive integer")
    if incoming == last_accepted + 1:
        return EdgeSequenceDisposition.NEXT
    if incoming > last_accepted + 1:
        return EdgeSequenceDisposition.GAP
    return EdgeSequenceDisposition.STALE


def verify_idempotent_replay(existing_fingerprint: str, incoming_fingerprint: str) -> bool:
    """Return True for an exact replay; reject event-ID reuse with changed content."""
    if not _SHA256.fullmatch(existing_fingerprint) or not _SHA256.fullmatch(incoming_fingerprint):
        raise EdgeEventContractError("event fingerprints must be lowercase SHA-256 hex")
    if not hmac.compare_digest(existing_fingerprint, incoming_fingerprint):
        raise EdgeEventContractError("event ID was reused with different content")
    return True
