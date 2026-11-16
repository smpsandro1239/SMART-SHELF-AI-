from datetime import date
from decimal import Decimal
import pytest
from app.sales_import_hourly import MAX_HOURLY_IMPORT_BYTES, MAX_HOURLY_IMPORT_ROWS, parse_hourly_sales_csv, parse_hourly_traffic_csv

SALES_HEADER = "product_id,business_date,hour_of_day,quantity,external_reference\n"
TRAFFIC_HEADER = "business_date,hour_of_day,customer_count,external_reference\n"

def test_parse_hourly_sales_csv_supports_utf8_bom_and_zero_quantity():
    payload = ("\ufeff" + SALES_HEADER + "42,2026-11-12,8,0,POS-42-20261112-08\n").encode("utf-8")
    rows = parse_hourly_sales_csv(payload)
    assert rows[0].product_id == 42
    assert rows[0].business_date == date(2026, 11, 12)
    assert rows[0].quantity == Decimal("0")

def test_parse_hourly_traffic_csv_accepts_zero_customers():
    rows = parse_hourly_traffic_csv((TRAFFIC_HEADER + "2026-11-12,8,0,TRAFFIC-08\n").encode())
    assert rows[0].customer_count == 0

@pytest.mark.parametrize("payload,message", [
    (b"", "empty"),
    ((SALES_HEADER + "42,2026-11-12,24,1,REF\n").encode(), "hour_of_day"),
    ((SALES_HEADER + "42,12-11-2026,8,1,REF\n").encode(), "business_date"),
    ((SALES_HEADER + "42,2026-11-12,8,NaN,REF\n").encode(), "quantity"),
    ((SALES_HEADER + "42,2026-11-12,8,-1,REF\n").encode(), "quantity"),
    ((SALES_HEADER + "42,2026-11-12,8,1,\n").encode(), "external_reference"),
])
def test_hourly_sales_csv_rejects_invalid_rows(payload, message):
    with pytest.raises(ValueError, match=message):
        parse_hourly_sales_csv(payload)

def test_hourly_csv_rejects_duplicate_external_references():
    payload = (SALES_HEADER + "42,2026-11-12,8,1,SAME\n43,2026-11-12,9,2,SAME\n").encode()
    with pytest.raises(ValueError, match="Duplicate external_reference"):
        parse_hourly_sales_csv(payload)

def test_hourly_traffic_csv_rejects_invalid_counts():
    with pytest.raises(ValueError, match="customer_count"):
        parse_hourly_traffic_csv((TRAFFIC_HEADER + "2026-11-12,8,-1,REF\n").encode())

def test_hourly_sales_csv_enforces_row_limit():
    rows = "".join(f"42,2026-11-12,8,1,REF-{i}\n" for i in range(MAX_HOURLY_IMPORT_ROWS + 1))
    with pytest.raises(ValueError, match="maximum"):
        parse_hourly_sales_csv((SALES_HEADER + rows).encode())


@pytest.mark.parametrize("payload,message", [
    ((SALES_HEADER + "42,2026-W46-1,8,1,REF\n").encode(), "business_date"),
    ((SALES_HEADER + "4_2,2026-11-12,8,1,REF\n").encode(), "product_id"),
    ((SALES_HEADER + "42,2026-11-12,1_2,1,REF\n").encode(), "hour_of_day"),
    ((TRAFFIC_HEADER + "2026-11-12,8,2_000,REF\n").encode(), "customer_count"),
    ((TRAFFIC_HEADER + "2026-11-12,8,1,REF-\x01-1\n").encode(), "external_reference"),
])
def test_hourly_import_rejects_noncanonical_dates_numbers_and_controls(payload, message):
    with pytest.raises(ValueError, match=message):
        if payload.startswith(SALES_HEADER.encode()):
            parse_hourly_sales_csv(payload)
        else:
            parse_hourly_traffic_csv(payload)


def test_hourly_import_rejects_nul_bytes():
    with pytest.raises(ValueError, match="NUL"):
        parse_hourly_sales_csv((SALES_HEADER + "42,2026-11-12,8,1,REF\n").encode() + b"\x00")


def test_hourly_import_enforces_byte_limit():
    with pytest.raises(ValueError, match="maximum file size"):
        parse_hourly_sales_csv(b"x" * (MAX_HOURLY_IMPORT_BYTES + 1))


@pytest.mark.parametrize(
    ("payload", "parser", "message"),
    [
        (
            (SALES_HEADER.replace("product_id", "product_id,product_id", 1)
             + "42,43,2026-11-12,8,1,REF-1" + chr(10)).encode(),
            parse_hourly_sales_csv,
            "duplicate column",
        ),
        (
            (TRAFFIC_HEADER.replace("business_date", "business_date,business_date", 1)
             + "2026-11-12,2026-11-13,8,1,REF-1" + chr(10)).encode(),
            parse_hourly_traffic_csv,
            "duplicate column",
        ),
        (
            (SALES_HEADER + "42,2026-11-12,8,1,REF-1,EXTRA" + chr(10)).encode(),
            parse_hourly_sales_csv,
            "Too many columns",
        ),
        (
            (TRAFFIC_HEADER + "2026-11-12,8,1,REF-1,EXTRA" + chr(10)).encode(),
            parse_hourly_traffic_csv,
            "Too many columns",
        ),
    ],
)
def test_hourly_import_rejects_duplicate_headers_and_extra_columns(payload, parser, message):
    with pytest.raises(ValueError, match=message):
        parser(payload)
