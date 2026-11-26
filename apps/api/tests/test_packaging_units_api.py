"""API contract for exact packaging calculations across UNIT, CASE and PALLET."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def test_replenishment_units_api_returns_exact_decimal_quantities_for_all_packaging_types():
    suffix = uuid4().hex[:8].upper()
    with TestClient(app) as client:
        store = client.post(
            "/api/v1/stores",
            json={"code": f"PACK-{suffix}", "name": "Loja embalagens"},
        )
        assert store.status_code == 201, store.text
        product = client.post(
            "/api/v1/products",
            json={"sku": f"PACK-SKU-{suffix}", "name": "Produto pesado", "unit": "kg"},
        )
        assert product.status_code == 201, product.text
        product_id = product.json()["id"]

        levels = [
            {"code": "UNIT", "name": "Unidade", "package_type": "UNIT", "base_units_per_package": 1},
            {"code": "CASE", "name": "Caixa", "package_type": "CASE", "base_units_per_package": 12},
            {"code": "PALLET", "name": "Palete", "package_type": "PALLET", "base_units_per_package": 720},
        ]
        for level in levels:
            response = client.post(
                "/api/v1/warehouse/product-packaging",
                json={
                    "product_id": product_id,
                    **level,
                    "is_ordering_unit": level["code"] == "PALLET",
                    "is_replenishment_unit": level["code"] == "CASE",
                },
            )
            assert response.status_code == 201, response.text

        case_open = client.get(
            "/api/v1/warehouse/replenishment-units",
            params={
                "store_id": store.json()["id"],
                "product_id": product_id,
                "required_base_units": "20.125",
                "packaging_code": "CASE",
                "allow_open_package": "true",
            },
        )
        assert case_open.status_code == 200, case_open.text
        opened = case_open.json()
        assert opened["base_unit"] == "kg"
        assert opened["base_units_per_package_exact"] == "12.000"
        assert opened["required_base_units_exact"] == "20.125"
        assert opened["package_count"] == 1
        assert opened["opened_package_count"] == 1
        assert opened["loose_base_units_exact"] == "8.125"
        assert opened["planned_base_units_exact"] == "20.125"
        assert opened["excess_base_units_exact"] == "0.000"
        assert opened["automatic_stock_movement_allowed"] is False

        case_sealed = client.get(
            "/api/v1/warehouse/replenishment-units",
            params={
                "store_id": store.json()["id"],
                "product_id": product_id,
                "required_base_units": "20.125",
                "packaging_code": "CASE",
                "allow_open_package": "false",
            },
        )
        assert case_sealed.status_code == 200, case_sealed.text
        assert case_sealed.json()["package_count"] == 2
        assert case_sealed.json()["planned_base_units_exact"] == "24.000"
        assert case_sealed.json()["excess_base_units_exact"] == "3.875"

        unit = client.get(
            "/api/v1/warehouse/replenishment-units",
            params={
                "store_id": store.json()["id"],
                "product_id": product_id,
                "required_base_units": "20.125",
                "packaging_code": "UNIT",
            },
        )
        assert unit.status_code == 200, unit.text
        assert unit.json()["package_type"] == "UNIT"
        assert unit.json()["package_count"] == 21
        assert unit.json()["planned_base_units_exact"] == "21.000"

        pallet = client.get(
            "/api/v1/warehouse/replenishment-units",
            params={
                "store_id": store.json()["id"],
                "product_id": product_id,
                "required_base_units": "721.125",
                "packaging_code": "PALLET",
            },
        )
        assert pallet.status_code == 200, pallet.text
        assert pallet.json()["package_type"] == "PALLET"
        assert pallet.json()["package_count"] == 2
        assert pallet.json()["planned_base_units_exact"] == "1440.000"
        assert pallet.json()["excess_base_units_exact"] == "718.875"


def test_packaging_factor_rejects_precision_that_database_would_silently_round():
    suffix = uuid4().hex[:8].upper()
    with TestClient(app) as client:
        product = client.post(
            "/api/v1/products",
            json={"sku": f"PACK-PRECISION-{suffix}", "name": "Produto com embalagem"},
        )
        assert product.status_code == 201, product.text
        product_id = product.json()["id"]

        valid = client.post(
            "/api/v1/warehouse/product-packaging",
            json={
                "product_id": product_id,
                "code": "CASE-VALID",
                "name": "Caixa fraccionária válida",
                "package_type": "CASE",
                "base_units_per_package": "12.125",
            },
        )
        assert valid.status_code == 201, valid.text
        assert valid.json()["base_units_per_package"] == 12.125

        invalid = client.post(
            "/api/v1/warehouse/product-packaging",
            json={
                "product_id": product_id,
                "code": "CASE-INVALID",
                "name": "Caixa com precisão inválida",
                "package_type": "CASE",
                "base_units_per_package": "12.1254",
            },
        )
        assert invalid.status_code == 422, invalid.text

        listed = client.get(
            "/api/v1/warehouse/product-packaging",
            params={"product_id": product_id},
        )
        assert listed.status_code == 200, listed.text
        assert [level["code"] for level in listed.json()] == ["CASE-VALID"]
