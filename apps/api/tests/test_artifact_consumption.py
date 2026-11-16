from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app import artifact_consumption as consumption
from app.artifact_consumption import (
    ArtifactAccessDenied,
    ArtifactIntegrityError,
    consume_external_artifact_bytes,
)
from app import models
from app.artifact_inventory_signing import inventory_signature, canonical_inventory_payload


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model
        self.conditions = []

    def join(self, *args, **kwargs):
        return self

    def filter(self, *conditions):
        self.conditions.extend(conditions)
        return self

    def order_by(self, *ordering):
        return self

    def _rows(self):
        value = self.session.records.get(self.model)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    def _matches(self, record):
        from sqlalchemy.sql import operators

        for condition in self.conditions:
            key = getattr(getattr(condition, "left", None), "key", None)
            right = getattr(condition, "right", None)
            expected = getattr(right, "value", object())
            if key is None or expected.__class__ is object:
                continue
            actual = getattr(record, key, None)
            if condition.operator is operators.eq and actual != expected:
                return False
            if condition.operator is operators.in_op and actual not in expected:
                return False
        return True

    def with_for_update(self, *args, **kwargs):
        self.session.locked_queries += 1
        return self

    def populate_existing(self):
        return self

    def first(self):
        rows = [row for row in self._rows() if self._matches(row)]
        return rows[0] if rows else None

    def all(self):
        return [row for row in self._rows() if self._matches(row)]


class FakeSession:
    def __init__(self, records):
        self.records = records
        self.locked_queries = 0
        self.rolled_back = False
        self.closed = False

    def query(self, model):
        return FakeQuery(self, model)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def fixture_session(*, retention_status="ACTIVE", legal_hold=False, event=None):
    payload = b"external artifact bytes"
    digest = sha256(payload).hexdigest()
    image = SimpleNamespace(id=7, store_id=4, retention_status=retention_status, legal_hold=legal_hold)
    artifact = SimpleNamespace(
        id=31,
        parent_reference_id=None,
        shelf_image_id=7,
        store_id=4,
        external_system="object-store-a",
        artifact_type="CROP",
        external_reference="bucket/crops/31.jpg",
        sha256=digest,
    )
    snapshot = SimpleNamespace(
        inventory_complete=True,
        generated_at=NOW - timedelta(minutes=2),
        verified_at=NOW - timedelta(minutes=1),
        inventory_manifest=[{
            "artifact_type": "CROP",
            "external_reference": "bucket/crops/31.jpg",
            "sha256": digest,
            "state": "PRESENT",
        }],
        artifact_count=1,
        present_count=1,
        absent_count=0,
        shelf_image_id=7,
        store_id=4,
        external_system="object-store-a",
        snapshot_id="snapshot-31",
        source_signature="",
        manifest_sha256="",
    )
    secret = "test-inventory-signing-secret-which-is-long-enough"
    snapshot.source_signature = inventory_signature(
        image_id=7, store_id=4, external_system="object-store-a",
        snapshot_id="snapshot-31", generated_at=snapshot.generated_at,
        entries=snapshot.inventory_manifest, secret=secret, inventory_complete=True,
    )
    snapshot.manifest_sha256 = sha256(canonical_inventory_payload(
        image_id=7, store_id=4, external_system="object-store-a",
        snapshot_id="snapshot-31", generated_at=snapshot.generated_at,
        entries=snapshot.inventory_manifest, inventory_complete=True,
    )).hexdigest()
    integration = SimpleNamespace(status="ACTIVE", external_system="object-store-a", store_id=4)
    if event is not None:
        event.artifact_reference_id = getattr(event, "artifact_reference_id", 31)
        event.shelf_image_id = getattr(event, "shelf_image_id", 7)
        event.store_id = getattr(event, "store_id", 4)
        event.sequence_number = getattr(event, "sequence_number", 1)
    records = {
        models.ShelfImage: image,
        models.ShelfImageArtifactReference: artifact,
        models.StoreExternalIntegration: integration,
        models.ShelfImageArtifactInventorySnapshot: snapshot,
        models.ShelfImageArtifactDispositionEvent: event,
    }
    session = FakeSession(records)
    return session, payload


def call(session, fetcher, **overrides):
    args = {
        "image_id": 7,
        "artifact_id": 31,
        "store_id": 4,
        "fetch_bytes": fetcher,
        "session_factory": lambda: session,
        "now": NOW,
    }
    args.update(overrides)
    original_keys = consumption.settings.artifact_inventory_hmac_keys_json
    consumption.settings.artifact_inventory_hmac_keys_json = '{"object-store-a":"test-inventory-signing-secret-which-is-long-enough","archive-store-b":"test-inventory-signing-secret-which-is-long-enough"}'
    try:
        return consume_external_artifact_bytes(**args)
    finally:
        consumption.settings.artifact_inventory_hmac_keys_json = original_keys


def test_sqlite_style_naive_persisted_timestamps_are_interpreted_as_utc():
    session, payload = fixture_session()
    snapshot = session.records[models.ShelfImageArtifactInventorySnapshot]
    snapshot.generated_at = snapshot.generated_at.replace(tzinfo=None)
    snapshot.verified_at = snapshot.verified_at.replace(tzinfo=None)
    fetched = []

    result = call(session, lambda *args: fetched.append(args) or payload)

    assert result == payload
    assert fetched == [("object-store-a", "bucket/crops/31.jpg")]
    assert session.rolled_back and session.closed


def test_naive_persisted_disposition_timestamp_is_interpreted_as_utc():
    event = SimpleNamespace(
        event_type="REJECTED",
        created_at=(NOW - timedelta(minutes=3)).replace(tzinfo=None),
    )
    session, payload = fixture_session(event=event)
    fetched = []

    result = call(session, lambda *args: fetched.append(args) or payload)

    assert result == payload
    assert fetched == [("object-store-a", "bucket/crops/31.jpg")]


def test_fetch_completes_while_all_required_rows_are_locked():
    session, payload = fixture_session()
    observed = []

    def fetch(external_system, external_reference):
        observed.append((external_system, external_reference))
        assert session.locked_queries == 5
        assert not session.rolled_back
        assert not session.closed
        return payload

    result = call(session, fetch)

    assert result == payload
    assert observed == [("object-store-a", "bucket/crops/31.jpg")]
    assert session.rolled_back is True
    assert session.closed is True


@pytest.mark.parametrize(
    ("retention_status", "legal_hold", "reason"),
    [
        ("RESTRICTED", False, "source_image_not_active"),
        ("ACTIVE", True, "source_image_under_legal_hold"),
    ],
)
def test_restricted_source_never_reaches_provider(retention_status, legal_hold, reason):
    session, _ = fixture_session(retention_status=retention_status, legal_hold=legal_hold)
    fetched = []

    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")

    assert reason in error.value.decision.reasons
    assert fetched == []
    assert session.rolled_back and session.closed


def test_disposition_event_blocks_fetch():
    event = SimpleNamespace(event_type="PROPOSED", created_at=NOW - timedelta(seconds=30))
    session, _ = fixture_session(event=event)
    fetched = []

    with pytest.raises(ArtifactAccessDenied):
        call(session, lambda *args: fetched.append(args) or b"unexpected")

    assert fetched == []


def test_provider_bytes_must_match_declared_digest():
    session, _ = fixture_session()

    with pytest.raises(ArtifactIntegrityError):
        call(session, lambda *args: b"tampered bytes")

    assert session.rolled_back and session.closed


@pytest.mark.parametrize("deferred", [bytearray(b"bytes"), iter([b"bytes"])])
def test_provider_must_return_materialized_bytes(deferred):
    session, _ = fixture_session()

    with pytest.raises(TypeError, match="fully materialized bytes"):
        call(session, lambda *args: deferred)

    assert session.rolled_back and session.closed


def test_provider_failure_still_releases_transaction():
    session, _ = fixture_session()

    def fail(*args):
        assert session.locked_queries == 5
        raise TimeoutError("provider timeout")

    with pytest.raises(TimeoutError):
        call(session, fail)

    assert session.rolled_back and session.closed


def test_revoked_external_integration_never_reaches_provider():
    session, _ = fixture_session()
    session.records[models.StoreExternalIntegration].status = "REVOKED"
    fetched = []

    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")

    assert "external_integration_not_active" in error.value.decision.reasons
    assert fetched == []
    assert session.rolled_back and session.closed


def test_missing_inventory_snapshot_never_reaches_provider():
    session, _ = fixture_session()
    session.records[models.ShelfImageArtifactInventorySnapshot] = None
    fetched = []

    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")

    assert "inventory_missing" in error.value.decision.reasons
    assert fetched == []


def test_artifact_without_declared_digest_is_not_consumed():
    session, _ = fixture_session()
    session.records[models.ShelfImageArtifactReference].sha256 = None
    snapshot = session.records[models.ShelfImageArtifactInventorySnapshot]
    snapshot.inventory_manifest[0]["sha256"] = None
    secret = "test-inventory-signing-secret-which-is-long-enough"
    snapshot.source_signature = inventory_signature(
        image_id=7, store_id=4, external_system="object-store-a",
        snapshot_id="snapshot-31", generated_at=snapshot.generated_at,
        entries=snapshot.inventory_manifest, secret=secret, inventory_complete=True,
    )
    snapshot.manifest_sha256 = sha256(canonical_inventory_payload(
        image_id=7, store_id=4, external_system="object-store-a",
        snapshot_id="snapshot-31", generated_at=snapshot.generated_at,
        entries=snapshot.inventory_manifest, inventory_complete=True,
    )).hexdigest()
    fetched = []

    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")

    assert "artifact_sha256_not_declared" in error.value.decision.reasons
    assert fetched == []


def test_inventory_timestamp_equal_to_disposition_blocks_provider_fetch():
    event_time = NOW - timedelta(minutes=2)
    event = SimpleNamespace(event_type="REJECTED", created_at=event_time)
    session, _ = fixture_session(event=event)
    session.records[models.ShelfImageArtifactInventorySnapshot].generated_at = event_time
    fetched = []

    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")

    assert "inventory_predates_disposition" in error.value.decision.reasons
    assert fetched == []


def test_tampered_persisted_manifest_signature_blocks_provider_fetch():
    session, _ = fixture_session()
    session.records[models.ShelfImageArtifactInventorySnapshot].source_signature = "0" * 64
    fetched = []
    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")
    assert "inventory_integrity_unverified" in error.value.decision.reasons
    assert fetched == []


def test_persisted_manifest_digest_mismatch_blocks_provider_fetch():
    session, _ = fixture_session()
    session.records[models.ShelfImageArtifactInventorySnapshot].manifest_sha256 = "0" * 64
    fetched = []
    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")
    assert "inventory_integrity_unverified" in error.value.decision.reasons
    assert fetched == []


def test_persisted_manifest_reference_coverage_mismatch_blocks_provider_fetch():
    session, _ = fixture_session()
    session.records[models.ShelfImageArtifactInventorySnapshot].inventory_manifest[0]["external_reference"] = "other/path"
    fetched = []
    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")
    assert "inventory_integrity_unverified" in error.value.decision.reasons
    assert fetched == []


def test_missing_parent_in_locked_artifact_lineage_blocks_provider_fetch():
    session, _ = fixture_session()
    session.records[models.ShelfImageArtifactReference].parent_reference_id = 999
    fetched = []

    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")

    assert "artifact_parent_missing" in error.value.decision.reasons
    assert fetched == []
    assert session.rolled_back and session.closed


def test_parent_in_another_external_system_blocks_child_before_provider_fetch():
    session, _ = fixture_session()
    child = session.records[models.ShelfImageArtifactReference]
    child.parent_reference_id = 30
    parent_payload = b"parent artifact bytes"
    parent_digest = sha256(parent_payload).hexdigest()
    parent = SimpleNamespace(
        id=30,
        parent_reference_id=None,
        shelf_image_id=7,
        store_id=4,
        external_system="archive-store-b",
        artifact_type="DATASET_COPY",
        external_reference="archive/datasets/source.zip",
        sha256=parent_digest,
    )
    parent_snapshot = SimpleNamespace(
        inventory_complete=True,
        generated_at=NOW - timedelta(minutes=2),
        verified_at=NOW - timedelta(minutes=1),
        inventory_manifest=[{
            "artifact_type": "DATASET_COPY",
            "external_reference": parent.external_reference,
            "sha256": parent_digest,
            "state": "PRESENT",
        }],
        artifact_count=1,
        present_count=1,
        absent_count=0,
        shelf_image_id=7,
        store_id=4,
        external_system="archive-store-b",
        snapshot_id="snapshot-parent-30",
        source_signature="",
        manifest_sha256="",
    )
    secret = "test-inventory-signing-secret-which-is-long-enough"
    parent_snapshot.source_signature = inventory_signature(
        image_id=7,
        store_id=4,
        external_system="archive-store-b",
        snapshot_id=parent_snapshot.snapshot_id,
        generated_at=parent_snapshot.generated_at,
        entries=parent_snapshot.inventory_manifest,
        secret=secret,
        inventory_complete=True,
    )
    parent_snapshot.manifest_sha256 = sha256(canonical_inventory_payload(
        image_id=7,
        store_id=4,
        external_system="archive-store-b",
        snapshot_id=parent_snapshot.snapshot_id,
        generated_at=parent_snapshot.generated_at,
        entries=parent_snapshot.inventory_manifest,
        inventory_complete=True,
    )).hexdigest()
    session.records[models.ShelfImageArtifactReference] = [child, parent]
    session.records[models.StoreExternalIntegration] = [
        session.records[models.StoreExternalIntegration],
        SimpleNamespace(status="ACTIVE", external_system="archive-store-b", store_id=4),
    ]
    session.records[models.ShelfImageArtifactInventorySnapshot] = [
        session.records[models.ShelfImageArtifactInventorySnapshot],
        parent_snapshot,
    ]
    session.records[models.ShelfImageArtifactDispositionEvent] = [
        SimpleNamespace(
            artifact_reference_id=30,
            shelf_image_id=7,
            store_id=4,
            sequence_number=1,
            event_type="PROPOSED",
            created_at=NOW - timedelta(seconds=30),
        )
    ]
    fetched = []

    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")

    assert "ancestor_artifact_disposition_pending_or_approved" in error.value.decision.reasons
    assert fetched == []
    assert session.rolled_back and session.closed


def test_parent_in_another_external_system_with_revoked_integration_blocks_child():
    session, _ = fixture_session()
    child = session.records[models.ShelfImageArtifactReference]
    child.parent_reference_id = 30
    parent = SimpleNamespace(
        id=30,
        parent_reference_id=None,
        shelf_image_id=7,
        store_id=4,
        external_system="archive-store-b",
        artifact_type="DATASET_COPY",
        external_reference="archive/datasets/source.zip",
        sha256="b" * 64,
    )
    session.records[models.ShelfImageArtifactReference] = [child, parent]
    session.records[models.StoreExternalIntegration] = [
        session.records[models.StoreExternalIntegration],
        SimpleNamespace(status="REVOKED", external_system="archive-store-b", store_id=4),
    ]
    fetched = []

    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")

    assert "ancestor_external_integration_not_active" in error.value.decision.reasons
    assert fetched == []
    assert session.rolled_back and session.closed
