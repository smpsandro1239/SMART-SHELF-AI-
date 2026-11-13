import pytest

from app.forecast_evaluation import (
    ForecastObservation,
    evaluate_forecasts,
)


def test_evaluation_calculates_error_metrics_and_bias():
    result = evaluate_forecasts([
        ForecastObservation(actual=10, predicted=12, store_id=1, product_id=5),
        ForecastObservation(actual=20, predicted=18, store_id=1, product_id=6),
    ])

    assert result.status == "AVAILABLE"
    assert result.observations == 2
    assert result.mae == 2
    assert result.rmse == 2
    assert result.wape == 0.1333
    assert result.bias == 0
    assert result.mape == 0.15
    assert result.by_store[0]["key"] == "1"
    assert result.by_store[0]["observations"] == 2
    assert len(result.by_product) == 2


def test_zero_actuals_are_counted_but_excluded_from_mape():
    result = evaluate_forecasts([
        {"actual": 0, "predicted": 3, "store_id": "A"},
        {"actual": 10, "predicted": 12, "store_id": "A"},
    ])

    assert result.zero_actual_observations == 1
    assert result.mae == 2.5
    assert result.wape == 0.5
    assert result.mape == 0.2


def test_wape_and_mape_are_undefined_when_all_actuals_are_zero():
    result = evaluate_forecasts([
        {"actual": 0, "predicted": 1},
        {"actual": 0, "predicted": 2},
    ])

    assert result.wape is None
    assert result.mape is None
    assert result.zero_actual_observations == 2


def test_insufficient_history_does_not_hide_available_metrics():
    result = evaluate_forecasts(
        [{"actual": 4, "predicted": 5}],
        minimum_observations=3,
    )

    assert result.status == "INSUFFICIENT_HISTORY"
    assert result.observations == 1
    assert result.mae == 1


def test_empty_input_returns_insufficient_history_without_fake_zeros():
    result = evaluate_forecasts([], minimum_observations=2)

    assert result.status == "INSUFFICIENT_HISTORY"
    assert result.observations == 0
    assert result.mae is None
    assert result.wape is None


@pytest.mark.parametrize(
    "row",
    [
        {"actual": True, "predicted": 1},
        {"actual": 1, "predicted": False},
        {"actual": -1, "predicted": 1},
        {"actual": 1, "predicted": -1},
        {"actual": float("nan"), "predicted": 1},
        {"actual": 1, "predicted": float("inf")},
        {"predicted": 1},
        {"actual": 1},
    ],
)
def test_invalid_or_incomplete_observations_are_rejected(row):
    with pytest.raises(ValueError):
        evaluate_forecasts([row])


@pytest.mark.parametrize("minimum", [0, -1, True, 1.5])
def test_minimum_observations_must_be_a_positive_integer(minimum):
    with pytest.raises(ValueError):
        evaluate_forecasts([], minimum_observations=minimum)


def test_bias_sign_explains_over_and_under_forecasting():
    over = evaluate_forecasts([{"actual": 10, "predicted": 13}])
    under = evaluate_forecasts([{"actual": 10, "predicted": 7}])

    assert over.bias == 3
    assert under.bias == -3
