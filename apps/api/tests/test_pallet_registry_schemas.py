import pytest
from pydantic import ValidationError

from app.schemas import (
    PalletRotationPolicyCreate,
    PalletRotationPolicyUpdate,
    StorePalletCreate,
)


def pallet_payload(**overrides):
    values = {
        "store_id": 1,
        "product_id": 7,
        "packaging_level_id": 12,
        "pallet_code": "PAL-0001",
        "lot_code": "LOT-2026-11",
        "expiry_date": "2027-06-30",
        "base_quantity": 720,
        "status": "READY",
        "location_type": "WAREHOUSE",
        "location_code": "ARZ-A-01",
    }
    values.update(overrides)
    return values


def test_valid_pallet_registration_payload_preserves_lot_and_expiry():
    payload = StorePalletCreate(**pallet_payload())
    assert payload.base_quantity == 720
    assert payload.lot_code == "LOT-2026-11"
    assert str(payload.expiry_date) == "2027-06-30"


@pytest.mark.parametrize("quantity", [-1, float("nan"), float("inf")])
def test_pallet_quantity_must_be_finite_and_nonnegative(quantity):
    with pytest.raises(ValidationError):
        StorePalletCreate(**pallet_payload(base_quantity=quantity))


def test_pallet_status_and_location_are_restricted_to_known_values():
    with pytest.raises(ValidationError):
        StorePalletCreate(**pallet_payload(status="SWAPPED"))
    with pytest.raises(ValidationError):
        StorePalletCreate(**pallet_payload(location_type="CUSTOMER_CAR"))


def test_rotation_policy_threshold_is_configurable_per_store_product():
    policy = PalletRotationPolicyCreate(
        store_id=1, product_id=7, threshold_ratio=0.35, is_enabled=True
    )
    assert policy.threshold_ratio == pytest.approx(0.35)


@pytest.mark.parametrize("threshold", [0, -0.1, 1.01, float("nan"), float("inf")])
def test_rotation_policy_rejects_invalid_threshold(threshold):
    with pytest.raises(ValidationError):
        PalletRotationPolicyCreate(
            store_id=1, product_id=7, threshold_ratio=threshold
        )


def test_rotation_policy_update_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        PalletRotationPolicyUpdate()


def test_rotation_policy_can_be_disabled_without_changing_threshold():
    update = PalletRotationPolicyUpdate(is_enabled=False)
    assert update.is_enabled is False
    assert update.threshold_ratio is None
