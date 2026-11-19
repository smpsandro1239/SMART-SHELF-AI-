import pytest

from app.shelf_layout import ShelfCell, compare_detections_to_cells, group_detections_into_rows


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



def cell(cell_id, x1, y1, x2, y2, expected_product_id=None, *, visible=True, occluded=False):
    return ShelfCell(
        cell_id=cell_id,
        x_min=x1,
        y_min=y1,
        x_max=x2,
        y_max=y2,
        expected_product_id=expected_product_id,
        is_visible=visible,
        is_occluded=occluded,
    )


def test_explicit_visible_cell_without_detection_is_empty_not_inventory_zero():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, expected_product_id=10)],
        [],
    )

    assert result[0].status == "EMPTY"
    assert result[0].expected_product_id == 10
    assert result[0].observed_product_ids == ()
    assert result[0].overlap_ratio == 0


@pytest.mark.parametrize("visible,occluded", [(False, False), (True, True)])
def test_unseen_or_occluded_cell_is_unknown_not_empty(visible, occluded):
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, visible=visible, occluded=occluded)],
        [],
    )

    assert result[0].status == "UNKNOWN"


def test_cell_detection_is_occupied_and_preserves_detection_provenance():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, expected_product_id=10)],
        [box(0.1, 0.1, 0.4, 0.9, 10)],
    )

    assert result[0].status == "OCCUPIED"
    assert result[0].observed_product_ids == (10,)
    assert result[0].detection_indices == (0,)
    assert result[0].overlap_ratio == pytest.approx(0.48)


def test_cell_with_only_wrong_sku_is_misplaced():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, expected_product_id=10)],
        [box(0.1, 0.1, 0.4, 0.9, 20)],
    )

    assert result[0].status == "MISPLACED"
    assert result[0].observed_product_ids == (20,)


def test_unidentified_detection_is_not_reported_as_empty():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0)],
        [box(0.1, 0.1, 0.4, 0.9, None)],
    )

    assert result[0].status == "OCCUPIED_UNIDENTIFIED"


def test_detection_outside_cell_does_not_fill_it():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0)],
        [box(0.7, 0.1, 0.9, 0.9, 10)],
    )

    assert result[0].status == "EMPTY"


def test_duplicate_cell_ids_and_invalid_overlap_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        compare_detections_to_cells(
            [cell("A1", 0, 0, 0.5, 1), cell("A1", 0.5, 0, 1, 1)],
            [],
        )
    with pytest.raises(ValueError, match="minimum_cell_overlap"):
        compare_detections_to_cells([], [], minimum_cell_overlap=0)



def test_cell_without_explicit_visibility_calibration_is_unknown():
    uncalibrated = ShelfCell("UNCALIBRATED", 0.0, 0.0, 1.0, 1.0)

    result = compare_detections_to_cells([uncalibrated], [])

    assert result[0].status == "UNKNOWN"


def test_detection_product_id_must_be_an_integer():
    with pytest.raises(ValueError, match="positive integer"):
        group_detections_into_rows([box(0.1, 0.1, 0.4, 0.4, 1.5)])
