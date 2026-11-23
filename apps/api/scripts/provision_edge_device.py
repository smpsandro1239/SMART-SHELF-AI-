"""Trusted operator CLI for Edge device lifecycle management.

Run from apps/api in a controlled environment with the application database
credentials configured. Never pipe the provision output to shared CI logs.
"""
from __future__ import annotations

import argparse
import json
import sys

from app.database import SessionLocal
from app.edge_device_service import (
    EdgeDeviceError,
    disable_edge_device,
    issue_edge_device_credential,
    register_edge_device,
    revoke_edge_device_credential,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Smart Shelf physical Edge devices.")
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register", help="Register a device and issue its first credential.")
    register.add_argument("--device-id", required=True)
    register.add_argument("--store-id", required=True, type=int)
    register.add_argument("--device-type", required=True, choices=("fixed_camera", "robot", "mobile", "gateway"))
    register.add_argument("--expires-in-seconds", type=int, default=30 * 24 * 60 * 60)

    rotate = commands.add_parser("rotate", help="Rotate a device credential and revoke the previous active credential.")
    rotate.add_argument("--device-id", required=True)
    rotate.add_argument("--expires-in-seconds", type=int, default=30 * 24 * 60 * 60)

    revoke = commands.add_parser("revoke", help="Revoke one credential by its public credential ID.")
    revoke.add_argument("--credential-id", required=True)

    disable = commands.add_parser("disable", help="Disable a device and revoke its active credentials.")
    disable.add_argument("--device-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        if args.command == "register":
            device = register_edge_device(
                db, device_id=args.device_id, store_id=args.store_id, device_type=args.device_type,
            )
            token, credential = issue_edge_device_credential(
                db, device_id=device.device_id, expires_in_seconds=args.expires_in_seconds,
            )
            # The bearer secret is returned exactly once. Persist only its digest.
            print(json.dumps({
                "device_id": device.device_id,
                "store_id": device.store_id,
                "credential_id": credential.credential_id,
                "expires_at": credential.expires_at.isoformat(),
                "credential": token,
                "warning": "Copy this credential to the device secret store now; it cannot be retrieved again.",
            }, indent=2))
        elif args.command == "rotate":
            token, credential = issue_edge_device_credential(
                db, device_id=args.device_id, expires_in_seconds=args.expires_in_seconds, rotate=True,
            )
            print(json.dumps({
                "device_id": args.device_id,
                "credential_id": credential.credential_id,
                "expires_at": credential.expires_at.isoformat(),
                "credential": token,
                "warning": "Previous active credentials were revoked. Store this credential securely now.",
            }, indent=2))
        elif args.command == "revoke":
            if not revoke_edge_device_credential(db, credential_id=args.credential_id):
                print("Credential not found or already revoked.", file=sys.stderr)
                return 2
            print("Credential revoked.")
        elif args.command == "disable":
            if not disable_edge_device(db, device_id=args.device_id):
                print("Device not found or already disabled.", file=sys.stderr)
                return 2
            print("Device disabled and active credentials revoked.")
        return 0
    except EdgeDeviceError as exc:
        print(f"Edge device operation rejected: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
