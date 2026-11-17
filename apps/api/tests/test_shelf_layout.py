import pytest

from app.shelf_layout import group_detections_into_rows


def box(x1, y1, x2, y2, product_id=None):
    return {
        "x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2,
        "product_id": product_id,
    }


def test_groups_products_into_rows_and_orders_positions_left_to_right():
    detections = [
        box(0.55, 0.12, 0.72, 0.38, 20),
        box(0.10, 0.10, 0.28, 0.40, 10),
        box(0.32, 0.11, 0.49, 0.39, 10),
        box(0.10, 0.58, 0.30, 0.88, None),
    ]

    rows = group_detections_into_rows(detections)

    assert len(rows) == 2
    assert [position.product_id for position in rows[0].positions] == [10, 10, 20]
    assert rows[0].visible_facings == 3
    assert rows[1].positions[0].product_id is None


def test_empty_detections_produce_no_rows():
    assert group_detections_into_rows([]) == ()


@pytest.mark.parametrize("threshold", [0, -0.1, 1.1])
def test_rejects_invalid_overlap_threshold(threshold):
    with pytest.raises(ValueError):
        group_detections_into_rows([], minimum_vertical_overlap=threshold)


def test_rejects_invalid_or_non_normalized_boxes():
    with pytest.raises(ValueError, match="normalized"):
        group_detections_into_rows([box(-0.1, 0.1, 0.3, 0.4)])


def test_touching_boxes_do_not_merge_into_same_row():
    rows = group_detections_into_rows([
        box(0.1, 0.1, 0.3, 0.3),
        box(0.4, 0.3, 0.6, 0.5),
    ])
    assert len(rows) == 2
