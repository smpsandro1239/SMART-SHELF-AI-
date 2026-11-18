"""Collect read-only PostgreSQL execution plans for image-derived API queries.

Run against a staging database or read replica with representative data:
    python scripts/postgres_image_query_plan_audit.py --store-id 12 --image-id 345

EXPLAIN ANALYZE executes each SELECT. The transaction is explicitly READ ONLY,
and each statement has a bounded timeout. No rows or schema objects are changed.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from sqlalchemy import text

from app.database import engine


def build_audit_queries(store_id: int, image_id: int) -> list[tuple[str, str, dict[str, int]]]:
    """Return the production query shapes used by image/evidence listing routes."""
    params = {"store_id": store_id, "image_id": image_id}
    return [
        (
            "active_shelf_images_by_store",
            """
            SELECT si.id
            FROM shelf_images AS si
            JOIN shelves AS s ON s.id = si.shelf_id
            JOIN zones AS z ON z.id = s.zone_id
            WHERE z.store_id = :store_id
              AND si.retention_status = 'ACTIVE'
            ORDER BY si.created_at DESC, si.id DESC
            LIMIT 100 OFFSET 0
            """,
            params,
        ),
        (
            "detections_by_image",
            """
            SELECT d.id
            FROM shelf_image_detections AS d
            WHERE d.shelf_image_id = :image_id
            ORDER BY d.id
            LIMIT 200 OFFSET 0
            """,
            params,
        ),
        (
            "ocr_matches_by_image",
            """
            SELECT m.id
            FROM shelf_image_ocr_matches AS m
            JOIN shelf_image_ocr_runs AS r ON r.id = m.run_id
            WHERE r.shelf_image_id = :image_id
            ORDER BY m.id DESC
            LIMIT 500 OFFSET 0
            """,
            params,
        ),
        (
            "ocr_evidence_by_image",
            """
            SELECT e.id
            FROM shelf_image_ocr_evidence AS e
            JOIN shelf_image_ocr_runs AS r ON r.id = e.run_id
            WHERE r.shelf_image_id = :image_id
            ORDER BY e.id DESC
            LIMIT 500 OFFSET 0
            """,
            params,
        ),
        (
            "retention_events_by_image",
            """
            SELECT e.id
            FROM shelf_image_retention_events AS e
            WHERE e.shelf_image_id = :image_id
            ORDER BY e.created_at ASC, e.id ASC
            LIMIT 100 OFFSET 0
            """,
            params,
        ),
        (
            "review_queue_latest_review_filter",
            """
            SELECT fe.id
            FROM shelf_image_fused_evidence AS fe
            JOIN shelf_image_detections AS d ON d.id = fe.detection_id
            JOIN shelf_images AS si ON si.id = d.shelf_image_id
            JOIN shelves AS s ON s.id = si.shelf_id
            JOIN zones AS z ON z.id = s.zone_id
            WHERE si.retention_status = 'ACTIVE'
              AND z.store_id = :store_id
              AND (
                  (SELECT MAX(r.created_at)
                   FROM detection_sku_reviews AS r
                   WHERE r.detection_id = d.id) IS NULL
                  OR
                  (SELECT MAX(r.created_at)
                   FROM detection_sku_reviews AS r
                   WHERE r.detection_id = d.id) < fe.created_at
              )
            ORDER BY
              CASE
                WHEN fe.status = 'CONFLICT' THEN 0
                WHEN fe.status = 'AMBIGUOUS' THEN 1
                WHEN fe.status = 'TEXT_ONLY' THEN 2
                WHEN fe.status = 'UNKNOWN' THEN 3
                WHEN fe.status = 'VISUAL_ONLY' THEN 4
                ELSE 5
              END ASC,
              fe.created_at ASC,
              fe.id ASC
            LIMIT 250 OFFSET 0
            """,
            params,
        ),
    ]


def _positive_id(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-id", type=_positive_id, required=True)
    parser.add_argument("--image-id", type=_positive_id, required=True)
    parser.add_argument(
        "--statement-timeout-ms",
        type=int,
        default=15000,
        choices=range(1000, 60001),
        metavar="1000..60000",
        help="per-query PostgreSQL timeout in milliseconds (default: 15000)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if engine.dialect.name != "postgresql":
        print("ERROR: this audit requires PostgreSQL; no query was executed.", file=sys.stderr)
        return 2

    reports: list[dict[str, Any]] = []
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(
                    text("SELECT set_config('statement_timeout', :timeout, true)"),
                    {"timeout": f"{args.statement_timeout_ms}ms"},
                )
                connection.execute(text("SET LOCAL lock_timeout = '2000ms'"))
                image_belongs_to_store = connection.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM shelf_images AS si
                            JOIN shelves AS s ON s.id = si.shelf_id
                            JOIN zones AS z ON z.id = s.zone_id
                            WHERE si.id = :image_id AND z.store_id = :store_id
                        )
                        """
                    ),
                    {"image_id": args.image_id, "store_id": args.store_id},
                ).scalar_one()
                if not image_belongs_to_store:
                    raise ValueError("image_id does not belong to the supplied store_id")

                for name, sql, params in build_audit_queries(args.store_id, args.image_id):
                    result = connection.execute(
                        text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON, TIMING OFF) " + sql),
                        params,
                    )
                    plan = result.scalar_one()
                    if isinstance(plan, str):
                        plan = json.loads(plan)
                    reports.append({"query": name, "plan": plan[0] if isinstance(plan, list) else plan})
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "completed_queries": [item["query"] for item in reports],
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps({"status": "ok", "plans": reports}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
