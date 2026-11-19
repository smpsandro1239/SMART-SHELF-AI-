"""PostgreSQL concurrency smoke for signed worker requests and replay protection."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4
import secrets

from app import models
from app.database import SessionLocal
from app.dataset_worker_credentials import (
    DatasetWorkerReplayError,
    issue_dataset_worker_credential,
    sign_dataset_worker_request,
    verify_dataset_worker_request,
)


def main():
    worker_id = f"pg-signed-worker-{uuid4().hex}"
    with SessionLocal() as db:
        token, credential = issue_dataset_worker_credential(
            db, worker_id=worker_id, scopes=["jobs:claim"], expires_in_seconds=3600
        )
        credential_id = credential.credential_id

    now = datetime.now(timezone.utc)
    timestamp = int(now.timestamp())
    nonce = secrets.token_urlsafe(24)
    method = "POST"
    target = "/internal/dataset-jobs/claim?queue=training"
    body = b'{"limit":1}'
    signature = sign_dataset_worker_request(
        bearer_token=token, method=method, request_target=target,
        body=body, timestamp=timestamp, nonce=nonce,
    )
    barrier = Barrier(2)

    def attempt():
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                principal = verify_dataset_worker_request(
                    db, bearer_token=token, method=method,
                    request_target=target, body=body, timestamp=timestamp,
                    nonce=nonce, signature=signature, required_scope="jobs:claim",
                    now=now,
                )
                return ("accepted", principal.worker_id)
            except DatasetWorkerReplayError:
                return ("replay", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: attempt(), range(2)))
    outcomes = sorted(result[0] for result in results)
    if outcomes != ["accepted", "replay"]:
        raise AssertionError(f"expected exactly one accepted request and one replay rejection, got {results}")
    with SessionLocal() as db:
        nonce_count = db.query(models.DatasetWorkerRequestNonce).filter_by(
            credential_id=credential_id
        ).count()
        if nonce_count != 1:
            raise AssertionError(f"expected one consumed nonce, got {nonce_count}")

    print(
        "PostgreSQL signed worker request smoke passed: request signature, "
        "scope enforcement and concurrent nonce replay rejection."
    )


if __name__ == "__main__":
    main()
