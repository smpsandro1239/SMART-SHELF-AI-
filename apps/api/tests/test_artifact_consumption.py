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


NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def join(self, *args, **kwargs):
        return self

    def filter(self, *conditions):
        return self

    def order_by(self, *ordering):
        return self

    def with_for_update(self, *args, **kwargs):
        self.session.locked_queries += 1
        return self

    def populate_existing(self):
        return self

    def first(self):
        return self.session.records.get(self.model)


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
    image = SimpleNamespace(retention_status=retention_status, legal_hold=legal_hold)
    artifact = SimpleNamespace(
        id=31,
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
    )
    integration = SimpleNamespace(status="ACTIVE")
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
    return consume_external_artifact_bytes(**args)


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
    session.records[models.ShelfImageArtifactInventorySnapshot].inventory_manifest[0]["sha256"] = None
    fetched = []

    with pytest.raises(ArtifactAccessDenied) as error:
        call(session, lambda *args: fetched.append(args) or b"unexpected")

    assert "artifact_sha256_not_declared" in error.value.decision.reasons
    assert fetched == []
