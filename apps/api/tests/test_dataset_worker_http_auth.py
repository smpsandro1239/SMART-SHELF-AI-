from datetime import datetime, timezone
import secrets

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.dataset_worker_credentials import issue_dataset_worker_credential, sign_dataset_worker_request
from app.dataset_worker_http import require_dataset_worker


@pytest.fixture
def worker_http_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        with factory() as db:
            yield db

    app = FastAPI()

    @app.post("/worker/jobs/claim")
    async def claim(request: Request, principal=Depends(require_dataset_worker("jobs:claim"))):
        return {
            "worker_id": principal.worker_id,
            "body": (await request.body()).decode("utf-8"),
        }

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    with factory() as db:
        token, credential = issue_dataset_worker_credential(
            db, worker_id="http-worker", scopes=["jobs:claim"], expires_in_seconds=3600
        )
        credential_id = credential.credential_id
    try:
        yield client, factory, token, credential_id
    finally:
        client.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def signed_headers(token, *, method, target, body, timestamp=None, nonce=None):
    timestamp = int(datetime.now(timezone.utc).timestamp()) if timestamp is None else timestamp
    nonce = secrets.token_urlsafe(24) if nonce is None else nonce
    signature = sign_dataset_worker_request(
        bearer_token=token, method=method, request_target=target,
        body=body, timestamp=timestamp, nonce=nonce,
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Worker-Timestamp": str(timestamp),
        "X-Worker-Nonce": nonce,
        "X-Worker-Signature": signature,
    }


def test_signed_worker_http_request_is_accepted_and_nonce_cannot_be_replayed(worker_http_client):
    client, factory, token, credential_id = worker_http_client
    body = b'{"limit":1}'
    target = "/worker/jobs/claim?queue=training"
    headers = signed_headers(token, method="POST", target=target, body=body)

    response = client.post(target, content=body, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"worker_id": "http-worker", "body": body.decode("utf-8")}

    replay = client.post(target, content=body, headers=headers)
    assert replay.status_code == 401
    with factory() as db:
        rows = db.query(models.DatasetWorkerRequestNonce).filter_by(
            credential_id=credential_id
        ).all()
        assert len(rows) == 1
        assert rows[0].nonce_sha256 not in headers["X-Worker-Nonce"]


@pytest.mark.parametrize(
    ("actual_target", "actual_body", "signed_target", "signed_body"),
    [
        ("/worker/jobs/claim", b'{"limit":2}', "/worker/jobs/claim", b'{"limit":1}'),
        ("/worker/jobs/claim?queue=other", b'{"limit":1}', "/worker/jobs/claim?queue=training", b'{"limit":1}'),
        ("/worker/jobs/claim", b'{"limit":1}', "/worker/jobs/other", b'{"limit":1}'),
    ],
)
def test_signature_binds_exact_target_and_body(
    worker_http_client, actual_target, actual_body, signed_target, signed_body
):
    client, _factory, token, _credential_id = worker_http_client
    headers = signed_headers(token, method="POST", target=signed_target, body=signed_body)
    response = client.post(actual_target, content=actual_body, headers=headers)
    assert response.status_code == 401


def test_signature_binds_http_method(worker_http_client):
    client, _factory, token, _credential_id = worker_http_client
    body = b"{}"
    headers = signed_headers(token, method="GET", target="/worker/jobs/claim", body=body)
    response = client.post("/worker/jobs/claim", content=body, headers=headers)
    assert response.status_code == 401


def test_stale_signed_request_is_rejected_without_consuming_nonce(worker_http_client):
    client, factory, token, credential_id = worker_http_client
    body = b"{}"
    timestamp = int(datetime.now(timezone.utc).timestamp()) - 61
    headers = signed_headers(
        token, method="POST", target="/worker/jobs/claim", body=body, timestamp=timestamp
    )
    response = client.post("/worker/jobs/claim", content=body, headers=headers)
    assert response.status_code == 401
    with factory() as db:
        assert db.query(models.DatasetWorkerRequestNonce).filter_by(
            credential_id=credential_id
        ).count() == 0


def test_insufficient_scope_is_rejected_before_nonce_consumption(worker_http_client):
    client, factory, _token, _credential_id = worker_http_client
    with factory() as db:
        token, credential = issue_dataset_worker_credential(
            db, worker_id="heartbeat-only", scopes=["jobs:heartbeat"],
            expires_in_seconds=3600,
        )
        credential_id = credential.credential_id
    body = b"{}"
    headers = signed_headers(token, method="POST", target="/worker/jobs/claim", body=body)
    response = client.post("/worker/jobs/claim", content=body, headers=headers)
    assert response.status_code == 403
    with factory() as db:
        assert db.query(models.DatasetWorkerRequestNonce).filter_by(
            credential_id=credential_id
        ).count() == 0


def test_invalid_signature_does_not_consume_nonce(worker_http_client):
    client, factory, token, credential_id = worker_http_client
    body = b"{}"
    headers = signed_headers(token, method="POST", target="/worker/jobs/claim", body=body)
    headers["X-Worker-Signature"] = "0" * 64
    response = client.post("/worker/jobs/claim", content=body, headers=headers)
    assert response.status_code == 401
    with factory() as db:
        assert db.query(models.DatasetWorkerRequestNonce).filter_by(
            credential_id=credential_id
        ).count() == 0
