"""Validate dataset worker credentials and immutable security audit on PostgreSQL."""

from uuid import uuid4

from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import SessionLocal
from app.dataset_worker_credentials import (
    DatasetWorkerAuthenticationError,
    authenticate_dataset_worker,
    disable_dataset_worker,
    issue_dataset_worker_credential,
    revoke_dataset_worker_credential,
)


def _rejected(operation, description):
    try:
        operation()
    except (IntegrityError, DatasetWorkerAuthenticationError):
        return
    raise AssertionError(f"expected rejection: {description}")


def main():
    worker_id = f"pg-dataset-worker-{uuid4().hex}"
    with SessionLocal() as db:
        first_token, first = issue_dataset_worker_credential(
            db, worker_id=worker_id,
            scopes=["jobs:claim", "jobs:heartbeat"],
            expires_in_seconds=3600,
        )
        assert first.secret_sha256 not in first_token
        principal = authenticate_dataset_worker(db, bearer_token=first_token)
        assert principal.worker_id == worker_id
        assert principal.scopes == frozenset({"jobs:claim", "jobs:heartbeat"})
        db.commit()

        events = db.query(models.DatasetWorkerEvent).filter_by(worker_id=worker_id).order_by(
            models.DatasetWorkerEvent.id
        ).all()
        assert [event.event_type for event in events] == ["WORKER_REGISTERED", "CREDENTIAL_ISSUED"]
        event_id = events[-1].id

        _rejected(
            lambda: db.execute(
                update(models.DatasetWorkerEvent)
                .where(models.DatasetWorkerEvent.id == event_id)
                .values(details={"tampered": True})
            ),
            "worker security event UPDATE",
        )
        db.rollback()

        _rejected(
            lambda: db.query(models.DatasetWorkerEvent).filter_by(id=event_id).delete(),
            "worker security event DELETE",
        )
        db.rollback()

        second_token, second = issue_dataset_worker_credential(
            db, worker_id=worker_id,
            scopes=["jobs:claim", "jobs:complete"],
            expires_in_seconds=3600, rotate=True,
        )
        db.commit()
        _rejected(
            lambda: authenticate_dataset_worker(db, bearer_token=first_token),
            "previous credential after rotation",
        )
        db.rollback()
        _rejected(
            lambda: db.execute(text("""
                UPDATE dataset_worker_credentials
                SET scopes = '["outputs:publish"]'::json
                WHERE credential_id = :credential_id
            """), {"credential_id": first.credential_id}),
            "direct mutation of a credential's scopes",
        )
        db.rollback()
        _rejected(
            lambda: db.execute(text("""
                UPDATE dataset_worker_credentials
                SET secret_sha256 = :digest
                WHERE credential_id = :credential_id
            """), {"credential_id": first.credential_id, "digest": "a" * 64}),
            "direct mutation of a credential secret digest",
        )
        db.rollback()
        assert authenticate_dataset_worker(db, bearer_token=second_token).worker_id == worker_id
        db.commit()

        assert revoke_dataset_worker_credential(db, credential_id=second.credential_id)
        db.commit()
        _rejected(
            lambda: authenticate_dataset_worker(db, bearer_token=second_token),
            "revoked credential",
        )
        db.rollback()

        disabled_id = f"{worker_id}-disabled"
        disabled_token, _disabled_credential = issue_dataset_worker_credential(
            db, worker_id=disabled_id, scopes=["jobs:claim"], expires_in_seconds=3600
        )
        db.commit()
        assert disable_dataset_worker(db, worker_id=disabled_id)
        db.commit()
        _rejected(
            lambda: db.execute(text("""
                UPDATE dataset_workers
                SET status = 'ACTIVE', disabled_at = NULL
                WHERE worker_id = :worker_id
            """), {"worker_id": disabled_id}),
            "direct reactivation of a disabled worker",
        )
        db.rollback()
        _rejected(
            lambda: authenticate_dataset_worker(db, bearer_token=disabled_token),
            "credential belonging to disabled worker",
        )
        db.rollback()

    print(
        "PostgreSQL dataset worker credential smoke passed: hashed secrets, "
        "individual identity, credential rotation/revocation, worker disablement "
        "and append-only security events."
    )


if __name__ == "__main__":
    main()
