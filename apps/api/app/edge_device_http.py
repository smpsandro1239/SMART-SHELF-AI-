"""HTTP boundary for authenticated Edge device event ingestion."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session
from app.database import get_db
from app.edge_device_service import (
    EdgeDeviceAuthenticationError, EdgeDeviceAuthorizationError, EdgeDeviceReplayError,
    authenticate_edge_device_request, ingest_edge_event,
)
from app.edge_event_contract import EdgeEventContractError, EdgeEventEnvelope
from app.edge_ingest_metrics import record_edge_ingest_outcome

router = APIRouter()

def _reject(status_code: int, category: str, detail: str, *, headers=None):
    record_edge_ingest_outcome("events_rejected")
    record_edge_ingest_outcome(category)
    raise HTTPException(status_code=status_code, detail=detail, headers=headers)

@router.post("/api/v1/edge/events", status_code=202)
async def receive_edge_event(
    request: Request, db: Session = Depends(get_db),
    authorization: str | None = Header(default=None, alias="Authorization"),
    edge_timestamp: str | None = Header(default=None, alias="X-Edge-Timestamp"),
    edge_nonce: str | None = Header(default=None, alias="X-Edge-Nonce"),
    edge_signature: str | None = Header(default=None, alias="X-Edge-Signature"),
):
    """Accept one signed event; identity and tenant come exclusively from the credential."""
    record_edge_ingest_outcome("events_received")
    if not isinstance(authorization, str):
        _reject(401, "authentication_rejected", "Invalid edge authentication",
                headers={"WWW-Authenticate": "Bearer"})
    scheme, separator, bearer_token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not bearer_token or " " in bearer_token:
        _reject(401, "authentication_rejected", "Invalid edge authentication",
                headers={"WWW-Authenticate": "Bearer"})
    if (not isinstance(edge_timestamp, str) or not edge_timestamp.isascii()
        or not edge_timestamp.isdigit() or len(edge_timestamp) > 12
        or not isinstance(edge_nonce, str) or not isinstance(edge_signature, str)):
        _reject(401, "authentication_rejected", "Invalid edge authentication")
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
            db, bearer_token=bearer_token, method=request.method,
            request_target=request_target, timestamp=int(edge_timestamp),
            nonce=edge_nonce, signature=edge_signature, body=body,
        )
    except EdgeDeviceAuthorizationError:
        _reject(403, "authorization_rejected", "Edge device scope is insufficient")
    except EdgeDeviceReplayError:
        _reject(409, "request_replay_rejected", "Edge request was already used")
    except (EdgeDeviceAuthenticationError, ValueError, UnicodeError):
        _reject(401, "authentication_rejected", "Invalid edge authentication",
                headers={"WWW-Authenticate": "Bearer"})
    try:
        event = EdgeEventEnvelope.model_validate_json(body)
    except ValidationError:
        _reject(422, "contract_rejected", "Invalid edge event contract")
    try:
        result = ingest_edge_event(db, principal=principal, event=event)
    except EdgeDeviceAuthorizationError:
        _reject(403, "authorization_rejected", "Edge event tenant binding is invalid")
    except EdgeDeviceReplayError:
        _reject(409, "sequence_conflicts", "Edge event sequence is not acceptable")
    except EdgeEventContractError:
        _reject(409, "event_id_conflicts", "Edge event identifier conflicts with stored content")
    except EdgeDeviceAuthenticationError:
        _reject(401, "authentication_rejected", "Edge device credential is no longer active")
    record_edge_ingest_outcome("events_duplicate" if result.duplicate else "events_accepted")
    return {
        "accepted": True, "event_id": result.event_id, "device_id": result.device_id,
        "sequence_number": result.sequence_number, "disposition": result.disposition,
        "duplicate": result.duplicate,
    }
