import pytest

from app.packaging_units import calculate_replenishment_packs, convert_to_base_units


def test_convert_case_and_pallet_to_base_units():
    assert convert_to_base_units(2, 12) == 24
    assert convert_to_base_units(1, 720) == 720


def test_full_case_replenishment_rounds_up_without_losing_units():
    result = calculate_replenishment_packs(
        required_base_units=20,
        base_units_per_package=12,
    )

    assert result["package_count"] == 2
    assert result["opened_package_count"] == 0
    assert result["loose_base_units"] == 0
    assert result["planned_base_units"] == 24
    assert result["excess_base_units"] == 4
    assert result["opened_package_required"] is False


def test_open_case_uses_case_plus_loose_base_units_when_allowed():
    result = calculate_replenishment_packs(
        required_base_units=20,
        base_units_per_package=12,
        allow_open_package=True,
    )

    assert result["package_count"] == 1
    assert result["opened_package_count"] == 1
    assert result["loose_base_units"] == 8
    assert result["planned_base_units"] == 20
    assert result["excess_base_units"] == 0
    assert result["opened_package_required"] is True


def test_fractional_pack_calculations_expose_exact_decimal_quantities():
    result = calculate_replenishment_packs(
        required_base_units="20.125",
        base_units_per_package="12.000",
        allow_open_package=True,
    )

    assert result["package_count"] == 1
    assert result["opened_package_count"] == 1
    assert result["required_base_units_exact"] == "20.125"
    assert result["loose_base_units_exact"] == "8.125"
    assert result["planned_base_units_exact"] == "20.125"
    assert result["excess_base_units_exact"] == "0.000"

    sealed = calculate_replenishment_packs(
        required_base_units="20.125",
        base_units_per_package="12.000",
        allow_open_package=False,
    )
    assert sealed["package_count"] == 2
    assert sealed["planned_base_units_exact"] == "24.000"
    assert sealed["excess_base_units_exact"] == "3.875"


def test_exact_multiple_does_not_create_loose_units():
    result = calculate_replenishment_packs(
        required_base_units=24,
        base_units_per_package=12,
        allow_open_package=True,
    )

    assert result["package_count"] == 2
    assert result["loose_base_units"] == 0
    assert result["exact_quantity_possible"] is True


def test_quantity_smaller_than_pack_uses_one_opened_pack():
    result = calculate_replenishment_packs(
        required_base_units=8,
        base_units_per_package=12,
        allow_open_package=True,
    )

    assert result["package_count"] == 0
    assert result["opened_package_count"] == 1
    assert result["loose_base_units"] == 8
    assert result["planned_base_units"] == 8


@pytest.mark.parametrize("quantity", [0, -1, float("nan"), float("inf"), True, "abc"])
def test_invalid_quantities_are_rejected(quantity):
    with pytest.raises(ValueError):
        calculate_replenishment_packs(
            required_base_units=quantity,
            base_units_per_package=12,
        )


@pytest.mark.parametrize("pack_size", [0, -1, float("nan"), float("inf"), True])
def test_invalid_package_size_is_rejected(pack_size):
    with pytest.raises(ValueError):
        convert_to_base_units(1, pack_size)
