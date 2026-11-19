from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.dataset_worker_credentials import (
    DatasetWorkerAuthenticationError,
    DatasetWorkerAuthorizationError,
    DatasetWorkerCredentialError,
    DATASET_WORKER_SCOPES,
    authenticate_dataset_worker,
    disable_dataset_worker,
    issue_dataset_worker_credential,
    require_dataset_worker_scope,
    revoke_dataset_worker_credential,
)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dataset-workers.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def issue(db, *, worker_id="worker-a", scopes=None, rotate=False):
    return issue_dataset_worker_credential(
        db,
        worker_id=worker_id,
        scopes=scopes or ["jobs:claim", "jobs:heartbeat"],
        rotate=rotate,
    )


def test_credential_is_individual_hashed_and_authenticates(db):
    token, record = issue(db)
    assert token.startswith(f"ssw1.{record.credential_id}.")
    assert record.secret_sha256 not in token
    assert record.secret_sha256 != token.split(".")[-1]
    assert len(record.secret_sha256) == 64

    principal = authenticate_dataset_worker(db, bearer_token=token)
    assert principal.worker_id == "worker-a"
    assert principal.credential_id == record.credential_id
    assert principal.scopes == frozenset({"jobs:claim", "jobs:heartbeat"})
    assert record.last_used_at is not None


def test_scope_authorization_is_explicit_and_least_privilege(db):
    token, _record = issue(db, scopes=["jobs:claim"])
    principal = authenticate_dataset_worker(db, bearer_token=token)
    require_dataset_worker_scope(principal, required_scope="jobs:claim")
    with pytest.raises(DatasetWorkerAuthorizationError):
        require_dataset_worker_scope(principal, required_scope="jobs:complete")
    with pytest.raises(DatasetWorkerAuthorizationError):
        require_dataset_worker_scope(principal, required_scope="admin:*")


@pytest.mark.parametrize("token", [
    "",
    "Bearer abc",
    "ssw1.invalid.secret",
    "ssw1." + "a" * 32 + "." + "x" * 43,
])
def test_malformed_or_unknown_credentials_are_rejected(db, token):
    with pytest.raises(DatasetWorkerAuthenticationError):
        authenticate_dataset_worker(db, bearer_token=token)


def test_wrong_secret_is_rejected(db):
    token, _record = issue(db)
    parts = token.split(".")
    tampered = ".".join((parts[0], parts[1], "A" * len(parts[2])))
    with pytest.raises(DatasetWorkerAuthenticationError):
        authenticate_dataset_worker(db, bearer_token=tampered)


def test_expired_credential_is_rejected(db):
    token, record = issue(db)
    record.expires_at = models.utc_now() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(DatasetWorkerAuthenticationError):
        authenticate_dataset_worker(db, bearer_token=token)


def test_revocation_invalidates_existing_credential(db):
    token, record = issue(db)
    assert revoke_dataset_worker_credential(db, credential_id=record.credential_id)
    assert not revoke_dataset_worker_credential(db, credential_id=record.credential_id)
    with pytest.raises(DatasetWorkerAuthenticationError):
        authenticate_dataset_worker(db, bearer_token=token)


def test_rotation_revokes_previous_secret_and_keeps_new_identity(db):
    old_token, old_record = issue(db)
    new_token, new_record = issue(db, rotate=True)
    db.refresh(old_record)
    assert old_record.revoked_at is not None
    assert old_record.replaced_by_credential_id == new_record.credential_id
    assert new_record.worker_id == old_record.worker_id
    with pytest.raises(DatasetWorkerAuthenticationError):
        authenticate_dataset_worker(db, bearer_token=old_token)
    assert authenticate_dataset_worker(db, bearer_token=new_token).worker_id == "worker-a"

    events = db.query(models.DatasetWorkerEvent).order_by(models.DatasetWorkerEvent.id).all()
    assert [event.event_type for event in events] == [
        "WORKER_REGISTERED", "CREDENTIAL_ISSUED", "CREDENTIAL_ROTATED"
    ]


def test_disabled_worker_invalidates_all_credentials(db):
    token, _record = issue(db)
    assert disable_dataset_worker(db, worker_id="worker-a")
    assert not disable_dataset_worker(db, worker_id="worker-a")
    with pytest.raises(DatasetWorkerAuthenticationError):
        authenticate_dataset_worker(db, bearer_token=token)
    with pytest.raises(DatasetWorkerCredentialError, match="disabled"):
        issue(db)


@pytest.mark.parametrize("scopes", [
    [],
    ["jobs:claim", "jobs:claim"],
    ["jobs:claim", "users:admin"],
    ["*"],
])
def test_invalid_scope_sets_are_rejected(db, scopes):
    with pytest.raises(DatasetWorkerCredentialError):
        issue(db, scopes=scopes)


@pytest.mark.parametrize("lifetime", [True, 0, 59, 90 * 24 * 60 * 60 + 1])
def test_invalid_credential_lifetime_is_rejected(db, lifetime):
    with pytest.raises(DatasetWorkerCredentialError):
        issue_dataset_worker_credential(
            db, worker_id="worker-a", scopes=["jobs:claim"],
            expires_in_seconds=lifetime,
        )


def test_worker_ids_are_not_silently_normalised(db):
    with pytest.raises(DatasetWorkerCredentialError):
        issue(db, worker_id=" worker-a ")
