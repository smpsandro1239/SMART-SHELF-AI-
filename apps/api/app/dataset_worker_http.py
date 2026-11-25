"""FastAPI dependency for signed, replay-resistant dataset worker requests.

This module defines an authentication boundary only. It does not mount or expose
job endpoints; handlers must opt in with Depends(require_dataset_worker(scope)).
"""
from __future__ import annotations

import re

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dataset_worker_credentials import (
    DATASET_WORKER_SCOPES,
    DatasetWorkerAuthenticationError,
    DatasetWorkerAuthorizationError,
    DatasetWorkerPrincipal,
    verify_dataset_worker_request,
)


def require_dataset_worker(required_scope: str):
    """Build a dependency that verifies a signed request and consumes its nonce."""
    if required_scope not in DATASET_WORKER_SCOPES:
        raise ValueError("unknown dataset worker scope")

    async def dependency(
        request: Request,
        db: Session = Depends(get_db),
        authorization: str | None = Header(default=None, alias="Authorization"),
        worker_timestamp: str | None = Header(default=None, alias="X-Worker-Timestamp"),
        worker_nonce: str | None = Header(default=None, alias="X-Worker-Nonce"),
        worker_signature: str | None = Header(default=None, alias="X-Worker-Signature"),
    ) -> DatasetWorkerPrincipal:
        if not isinstance(authorization, str):
            raise HTTPException(
                status_code=401, detail="Invalid worker request authentication",
                headers={"WWW-Authenticate": "Bearer"},
            )
        scheme, separator, bearer_token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not bearer_token or " " in bearer_token:
            raise HTTPException(
                status_code=401, detail="Invalid worker request authentication",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if (
            not isinstance(worker_timestamp, str)
            or not re.fullmatch(r"[0-9]{1,12}", worker_timestamp)
            or not isinstance(worker_nonce, str)
            or not isinstance(worker_signature, str)
        ):
            raise HTTPException(status_code=401, detail="Invalid worker request authentication")

        try:
            raw_path = request.scope.get("raw_path")
            if not isinstance(raw_path, bytes):
                raw_path = request.url.path.encode("ascii")
            raw_query = request.scope.get("query_string", b"")
            if not isinstance(raw_query, bytes):
                raise ValueError("invalid query string")
            request_target = raw_path.decode("ascii")
            if raw_query:
                request_target += "?" + raw_query.decode("ascii")
            body = await request.body()
            return verify_dataset_worker_request(
                db, bearer_token=bearer_token, method=request.method,
                request_target=request_target, body=body,
                timestamp=int(worker_timestamp), nonce=worker_nonce,
                signature=worker_signature, required_scope=required_scope,
            )
        except DatasetWorkerAuthorizationError as exc:
            raise HTTPException(status_code=403, detail="Worker scope is insufficient") from exc
        except (DatasetWorkerAuthenticationError, ValueError, UnicodeError) as exc:
            raise HTTPException(
                status_code=401, detail="Invalid worker request authentication",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    return dependency
