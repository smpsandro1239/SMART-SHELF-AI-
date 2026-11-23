"""HTTP boundary for authenticated Edge device event ingestion."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.edge_device_service import (
    EdgeDeviceAuthenticationError,
    EdgeDeviceAuthorizationError,
    EdgeDeviceReplayError,
    authenticate_edge_device_request,
    ingest_edge_event,
)
from app.edge_event_contract import EdgeEventContractError, EdgeEventEnvelope

router = APIRouter()


@router.post("/api/v1/edge/events", status_code=202)
async def receive_edge_event(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None, alias="Authorization"),
    edge_timestamp: str | None = Header(default=None, alias="X-Edge-Timestamp"),
    edge_nonce: str | None = Header(default=None, alias="X-Edge-Nonce"),
    edge_signature: str | None = Header(default=None, alias="X-Edge-Signature"),
):
    """Accept one signed event; identity and tenant come exclusively from the credential."""
    if not isinstance(authorization, str):
        raise HTTPException(status_code=401, detail="Invalid edge authentication",
                            headers={"WWW-Authenticate": "Bearer"})
    scheme, separator, bearer_token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not bearer_token or " " in bearer_token:
        raise HTTPException(status_code=401, detail="Invalid edge authentication",
                            headers={"WWW-Authenticate": "Bearer"})
    if (
        not isinstance(edge_timestamp, str)
        or not edge_timestamp.isascii()
        or not edge_timestamp.isdigit()
        or len(edge_timestamp) > 12
        or not isinstance(edge_nonce, str)
        or not isinstance(edge_signature, str)
    ):
        raise HTTPException(status_code=401, detail="Invalid edge authentication")

    body = await request.body()
    raw_path = request.scope.get("raw_path")
    if not isinstance(raw_path, bytes):
        raw_path = request.url.path.encode("ascii")
    raw_query = request.scope.get("query_string", b"")
    try:
        request_target = raw_path.decode("ascii")
        if raw_query:
            request_target += "?" + raw_query.decode("ascii")
        principal = authenticate_edge_device_request(
            db,
            bearer_token=bearer_token,
            method=request.method,
            request_target=request_target,
            timestamp=int(edge_timestamp),
            nonce=edge_nonce,
            signature=edge_signature,
            body=body,
        )
    except EdgeDeviceAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="Edge device scope is insufficient") from exc
    except EdgeDeviceReplayError as exc:
        raise HTTPException(status_code=409, detail="Edge request was already used") from exc
    except (EdgeDeviceAuthenticationError, ValueError, UnicodeError) as exc:
        raise HTTPException(
            status_code=401, detail="Invalid edge authentication",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        event = EdgeEventEnvelope.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid edge event contract") from exc

    try:
        result = ingest_edge_event(db, principal=principal, event=event)
    except EdgeDeviceAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="Edge event tenant binding is invalid") from exc
    except EdgeDeviceReplayError as exc:
        raise HTTPException(status_code=409, detail="Edge event sequence is not acceptable") from exc
    except EdgeEventContractError as exc:
        raise HTTPException(status_code=409, detail="Edge event identifier conflicts with stored content") from exc
    except EdgeDeviceAuthenticationError as exc:
        raise HTTPException(status_code=401, detail="Edge device credential is no longer active") from exc

    return {
        "accepted": True,
        "event_id": result.event_id,
        "device_id": result.device_id,
        "sequence_number": result.sequence_number,
        "disposition": result.disposition,
        "duplicate": result.duplicate,
    }
