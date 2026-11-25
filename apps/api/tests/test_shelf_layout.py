import pytest

from app.shelf_layout import ShelfCell, compare_detections_to_cells, group_detections_into_rows


def box(x1, y1, x2, y2, product_id=None, *, label=None, confidence=None):
    result = {
        "x_min": x1, "y_min": y1, "x_max": x2, "y_max": y2,
        "product_id": product_id,
    }
    if label is not None:
        result["label"] = label
    if confidence is not None:
        result["confidence"] = confidence
    return result


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



def cell(cell_id, x1, y1, x2, y2, expected_product_id=None, *, expected_facings=None, visible=True, occluded=False):
    return ShelfCell(
        cell_id=cell_id,
        x_min=x1,
        y_min=y1,
        x_max=x2,
        y_max=y2,
        expected_product_id=expected_product_id,
        expected_facings=expected_facings,
        is_visible=visible,
        is_occluded=occluded,
    )


def test_explicit_visible_cell_without_detection_is_unknown_not_empty():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, expected_product_id=10)],
        [],
    )

    assert result[0].status == "UNKNOWN"
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


def test_confident_empty_facing_detection_confirms_vacancy():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, expected_product_id=10, expected_facings=2)],
        [box(0.1, 0.1, 0.4, 0.9, label="empty_facing", confidence=0.95)],
    )

    assert result[0].status == "EMPTY"
    assert result[0].observed_product_ids == ()
    assert result[0].observed_facings == 0
    assert result[0].expected_facings == 2
    assert result[0].detection_indices == (0,)
    assert result[0].overlap_ratio == pytest.approx(0.48)


def test_low_confidence_empty_facing_is_unknown():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, expected_product_id=10)],
        [box(0.1, 0.1, 0.4, 0.9, label="empty_facing", confidence=0.79)],
    )

    assert result[0].status == "UNKNOWN"
    assert result[0].detection_indices == ()


def test_empty_facing_on_occluded_cell_is_unknown():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, visible=True, occluded=True)],
        [box(0.1, 0.1, 0.4, 0.9, label="empty_facing", confidence=0.99)],
    )

    assert result[0].status == "UNKNOWN"


def test_product_and_empty_facing_conflict_is_not_silently_resolved():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, expected_product_id=10)],
        [
            box(0.1, 0.1, 0.4, 0.9, 10, label="product", confidence=0.95),
            box(0.1, 0.1, 0.4, 0.9, label="empty_facing", confidence=0.96),
        ],
    )

    assert result[0].status == "CONFLICT"
    assert result[0].observed_product_ids == (10,)
    assert result[0].detection_indices == (0, 1)


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


def test_under_faced_cell_reports_observed_and_expected_front_facings():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, 10, expected_facings=3)],
        [
            box(0.05, 0.1, 0.22, 0.9, 10),
            box(0.25, 0.1, 0.42, 0.9, 10),
        ],
    )

    assert result[0].status == "UNDER_FACED"
    assert result[0].expected_facings == 3
    assert result[0].observed_facings == 2


def test_over_faced_cell_reports_excess_front_facings():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, 10, expected_facings=2)],
        [
            box(0.02, 0.1, 0.19, 0.9, 10),
            box(0.17, 0.1, 0.34, 0.9, 10),
            box(0.32, 0.1, 0.49, 0.9, 10),
        ],
    )

    assert result[0].status == "OVER_FACED"
    assert result[0].expected_facings == 2
    assert result[0].observed_facings == 3


def test_exact_planogram_facings_are_occupied():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, 10, expected_facings=2)],
        [
            box(0.05, 0.1, 0.22, 0.9, 10),
            box(0.25, 0.1, 0.42, 0.9, 10),
        ],
    )

    assert result[0].status == "OCCUPIED"
    assert result[0].observed_facings == result[0].expected_facings == 2


def test_wrong_sku_takes_precedence_over_facing_count():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, 10, expected_facings=3)],
        [box(0.1, 0.1, 0.4, 0.9, 20)],
    )

    assert result[0].status == "MISPLACED"
    assert result[0].observed_facings == 1


def test_unknown_sku_does_not_claim_under_facing():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, 10, expected_facings=3)],
        [box(0.1, 0.1, 0.4, 0.9, None)],
    )

    assert result[0].status == "OCCUPIED_UNIDENTIFIED"
    assert result[0].observed_facings == 1


def test_expected_facings_requires_expected_product_and_positive_integer():
    with pytest.raises(ValueError, match="requires expected_product_id"):
        cell("A1", 0, 0, 1, 1, expected_facings=2)
    with pytest.raises(ValueError, match="positive integer"):
        cell("A1", 0, 0, 1, 1, 10, expected_facings=0)
    with pytest.raises(ValueError, match="positive integer"):
        cell("A1", 0, 0, 1, 1, 10, expected_facings=True)


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

    assert result[0].status == "UNKNOWN"


def test_duplicate_cell_ids_and_invalid_overlap_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        compare_detections_to_cells(
            [cell("A1", 0, 0, 0.5, 1), cell("A1", 0.5, 0, 1, 1)],
            [],
        )
    with pytest.raises(ValueError, match="minimum_cell_overlap"):
        compare_detections_to_cells([], [], minimum_cell_overlap=0)
    with pytest.raises(ValueError, match="minimum_empty_confidence"):
        compare_detections_to_cells([], [], minimum_empty_confidence=1.1)
    with pytest.raises(ValueError, match="Detection confidence"):
        compare_detections_to_cells(
            [cell("A1", 0, 0, 1, 1, visible=True)],
            [box(0.1, 0.1, 0.9, 0.9, label="empty_facing", confidence=float("nan"))],
        )



def test_cell_without_explicit_visibility_calibration_is_unknown():
    uncalibrated = ShelfCell("UNCALIBRATED", 0.0, 0.0, 1.0, 1.0)

    result = compare_detections_to_cells([uncalibrated], [])

    assert result[0].status == "UNKNOWN"


def test_detection_product_id_must_be_an_integer():
    with pytest.raises(ValueError, match="positive integer"):
        group_detections_into_rows([box(0.1, 0.1, 0.4, 0.4, 1.5)])



def test_cell_is_misplaced_when_expected_and_wrong_skus_are_both_detected():
    result = compare_detections_to_cells(
        [cell("A1", 0.0, 0.0, 0.5, 1.0, expected_product_id=10)],
        [
            box(0.05, 0.1, 0.25, 0.9, 10),
            box(0.25, 0.1, 0.45, 0.9, 20),
        ],
    )

    assert result[0].status == "MISPLACED"
    assert result[0].observed_product_ids == (10, 20)


def test_overlapping_planogram_cells_are_rejected():
    with pytest.raises(ValueError, match="must not overlap"):
        compare_detections_to_cells(
            [
                cell("A1", 0.0, 0.0, 0.6, 1.0),
                cell("A2", 0.5, 0.0, 1.0, 1.0),
            ],
            [],
        )


def test_adjacent_planogram_cells_are_allowed():
    result = compare_detections_to_cells(
        [
            cell("A1", 0.0, 0.0, 0.5, 1.0),
            cell("A2", 0.5, 0.0, 1.0, 1.0),
        ],
        [],
    )

    assert [item.status for item in result] == ["UNKNOWN", "UNKNOWN"]
