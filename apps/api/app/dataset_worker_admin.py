"""Trusted local provisioning CLI for dataset worker credentials.

Run inside the API environment. The plaintext credential is printed once;
store it in a secret manager and never commit it to source control or logs.
"""
from __future__ import annotations

import argparse
import json

from app.database import SessionLocal
from app.dataset_worker_credentials import (
    DATASET_WORKER_SCOPES,
    disable_dataset_worker,
    issue_dataset_worker_credential,
    revoke_dataset_worker_credential,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision or revoke dataset worker credentials.")
    subparsers = parser.add_subparsers(dest="operation", required=True)

    for operation in ("issue", "rotate"):
        command = subparsers.add_parser(operation)
        command.add_argument("--worker-id", required=True)
        command.add_argument("--scope", action="append", required=True, choices=sorted(DATASET_WORKER_SCOPES))
        command.add_argument("--expires-in-seconds", type=int, default=30 * 24 * 60 * 60)

    revoke = subparsers.add_parser("revoke")
    revoke.add_argument("--credential-id", required=True)

    disable = subparsers.add_parser("disable")
    disable.add_argument("--worker-id", required=True)

    args = parser.parse_args()
    db = SessionLocal()
    try:
        if args.operation in {"issue", "rotate"}:
            token, credential = issue_dataset_worker_credential(
                db,
                worker_id=args.worker_id,
                scopes=args.scope,
                expires_in_seconds=args.expires_in_seconds,
                rotate=args.operation == "rotate",
            )
            print(json.dumps({
                "worker_id": credential.worker_id,
                "credential_id": credential.credential_id,
                "expires_at": credential.expires_at.isoformat(),
                "scopes": credential.scopes,
                "credential": token,
            }))
            return 0
        if args.operation == "revoke":
            print(json.dumps({"revoked": revoke_dataset_worker_credential(
                db, credential_id=args.credential_id
            )}))
            return 0
        print(json.dumps({"disabled": disable_dataset_worker(db, worker_id=args.worker_id)}))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
