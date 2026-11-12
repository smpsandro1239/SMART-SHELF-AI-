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


@pytest.mark.parametrize("payload", [
    {"threshold_ratio": None},
    {"is_enabled": None},
])
def test_rotation_policy_update_rejects_explicit_null_values(payload):
    with pytest.raises(ValidationError):
        PalletRotationPolicyUpdate(**payload)


def test_empty_pallet_requires_zero_quantity():
    payload = StorePalletCreate(**pallet_payload(status="EMPTY", base_quantity=0))
    assert payload.status == "EMPTY"


def test_nonempty_pallet_requires_positive_quantity():
    with pytest.raises(ValidationError):
        StorePalletCreate(**pallet_payload(status="READY", base_quantity=0))


def test_display_pallet_requires_sales_floor_location():
    with pytest.raises(ValidationError):
        StorePalletCreate(**pallet_payload(status="ON_DISPLAY", location_type="WAREHOUSE"))


def test_pallet_lifecycle_update_requires_expected_state_and_reason():
    from app.schemas import PalletLifecycleUpdate

    payload = PalletLifecycleUpdate(
        expected_status="READY",
        expected_base_quantity=720,
        status="ON_DISPLAY",
        location_type="SALES_FLOOR",
        reason="Colocação confirmada pelo supervisor",
    )
    assert payload.expected_status == "READY"
    assert payload.status == "ON_DISPLAY"


def test_pallet_lifecycle_update_rejects_empty_change():
    from app.schemas import PalletLifecycleUpdate

    with pytest.raises(ValidationError):
        PalletLifecycleUpdate(
            expected_status="READY",
            expected_base_quantity=720,
            reason="Sem alterações",
        )


@pytest.mark.parametrize("quantity", [-1, float("nan"), float("inf")])
def test_pallet_lifecycle_update_rejects_invalid_quantity(quantity):
    from app.schemas import PalletLifecycleUpdate

    with pytest.raises(ValidationError):
        PalletLifecycleUpdate(
            expected_status="READY",
            expected_base_quantity=720,
            base_quantity=quantity,
            reason="Contagem corrigida",
        )


def test_pallet_lifecycle_update_requires_reason():
    from app.schemas import PalletLifecycleUpdate

    with pytest.raises(ValidationError):
        PalletLifecycleUpdate(
            expected_status="READY",
            expected_base_quantity=720,
            status="ON_DISPLAY",
        )


def test_hourly_sales_schema_accepts_local_hour_and_zero_sales():
    from app.schemas import HourlySalesRecordCreate
    payload = HourlySalesRecordCreate(store_id=1, product_id=7, business_date="2026-11-10",
        hour_of_day=8, quantity=0, source="POS", external_reference="POS-STORE1-20261110-08")
    assert payload.hour_of_day == 8
    assert payload.quantity == 0


@pytest.mark.parametrize("hour", [-1, 24, 100])
def test_hourly_sales_schema_rejects_invalid_hour(hour):
    from app.schemas import HourlySalesRecordCreate
    with pytest.raises(ValidationError):
        HourlySalesRecordCreate(store_id=1, product_id=7, business_date="2026-11-10",
            hour_of_day=hour, quantity=4, source="POS", external_reference="hour-test")


def test_hourly_traffic_schema_accepts_zero_customer_count():
    from app.schemas import HourlyStoreTrafficRecordCreate
    payload = HourlyStoreTrafficRecordCreate(store_id=1, business_date="2026-11-10",
        hour_of_day=0, customer_count=0, source="POS", external_reference="TRAFFIC-STORE1-20261110-00")
    assert payload.customer_count == 0


def test_hourly_traffic_schema_rejects_negative_customer_count():
    from app.schemas import HourlyStoreTrafficRecordCreate
    with pytest.raises(ValidationError):
        HourlyStoreTrafficRecordCreate(store_id=1, business_date="2026-11-10",
            hour_of_day=12, customer_count=-1, source="POS", external_reference="traffic-invalid")
