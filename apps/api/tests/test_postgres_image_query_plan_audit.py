import pytest

from scripts.postgres_image_query_plan_audit import _positive_id, build_audit_queries


def test_image_query_audit_contains_only_bounded_selects():
    queries = build_audit_queries(store_id=7, image_id=42)

    assert {
        name for name, _, _ in queries
    } == {
        "active_shelf_images_by_store",
        "detections_by_image",
        "ocr_matches_by_image",
        "ocr_evidence_by_image",
        "retention_events_by_image",
        "review_queue_latest_review_filter",
    }

    for _, sql, params in queries:
        normalized = sql.strip().upper()
        assert normalized.startswith("SELECT")
        assert ";" not in sql
        assert "INSERT " not in normalized
        assert "UPDATE " not in normalized
        assert "DELETE " not in normalized
        assert "LIMIT " in normalized
        assert params == {"store_id": 7, "image_id": 42}


@pytest.mark.parametrize("value", ["0", "-1", "abc", ""])
def test_query_audit_rejects_invalid_ids(value):
    with pytest.raises(Exception):
        _positive_id(value)


def test_query_audit_accepts_positive_ids():
    assert _positive_id("42") == 42
