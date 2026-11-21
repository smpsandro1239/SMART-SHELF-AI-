"""Read-only audit of effective RBAC classifications for registered FastAPI routes.

Run from apps/api:
    python scripts/audit_api_route_policy.py
    python scripts/audit_api_route_policy.py --strict
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from fastapi.routing import APIRoute

from app.api_security_policy import classify_api_route
from app.main import app


def collect_route_policy() -> list[dict[str, str]]:
    """Return one deterministic record per API route method."""
    records: list[dict[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1/"):
            continue
        for method in sorted(route.methods or ()):
            records.append(
                {
                    "method": method,
                    "path": route.path,
                    "name": route.name,
                    "policy": classify_api_route(method, route.path),
                }
            )
    return sorted(records, key=lambda item: (item["path"], item["method"], item["name"]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero when any registered route method has no explicit policy",
    )
    args = parser.parse_args()

    records = collect_route_policy()
    counts = Counter(record["policy"] for record in records)
    fallback = [record for record in records if record["policy"] == "AUTHENTICATED_STAFF"]
    report = {
        "route_method_count": len(records),
        "policy_counts": dict(sorted(counts.items())),
        "fallback_count": len(fallback),
        "fallback_routes": fallback,
        "routes": records,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.strict and (unclassified or legacy_fallback) else 0


if __name__ == "__main__":
    raise SystemExit(main())
