import argparse

import pytest

from scripts.postgres_image_query_plan_audit import _positive_id, build_audit_queries


def test_image_query_audit_contains_bounded_first_and_deep_page_selects():
    queries = build_audit_queries(store_id=7, image_id=42, deep_offset=2500)
    names = {name for name, _, _ in queries}

    assert {
        "active_shelf_images_first_page",
        "active_shelf_images_deep_page",
        "detections_first_page",
        "detections_deep_page",
        "ocr_matches_first_page",
        "ocr_matches_deep_page",
        "ocr_evidence_first_page",
        "ocr_evidence_deep_page",
        "fused_evidence_deep_page",
        "retention_events_first_page",
        "retention_events_deep_page",
        "review_queue_latest_review_deep_page",
    } == names

    for _, sql, params in queries:
        normalized = sql.strip().upper()
        assert normalized.startswith("SELECT")
        assert ";" not in sql
        assert "INSERT " not in normalized
        assert "UPDATE " not in normalized
        assert "DELETE " not in normalized
        assert "LIMIT " in normalized
        assert params == {"store_id": 7, "image_id": 42, "deep_offset": 2500}

    assert any(":deep_offset" in sql for _, sql, _ in queries)


@pytest.mark.parametrize("value", ["0", "-1", "abc", ""])
def test_query_audit_rejects_invalid_ids(value):
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_id(value)


def test_query_audit_accepts_positive_ids():
    assert _positive_id("42") == 42
