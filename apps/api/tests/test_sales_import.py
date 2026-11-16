from datetime import date
from decimal import Decimal

import pytest

from app.sales_import import MAX_IMPORT_ROWS, parse_daily_sales_csv


HEADER = "product_id,sales_date,quantity,external_reference\n"


def test_parse_daily_sales_csv_supports_utf8_bom_and_zero_sales():
    payload = ("\ufeff" + HEADER + "12,2026-11-12,0,POS-12-20261112\n").encode("utf-8")
    rows = parse_daily_sales_csv(payload)
    assert len(rows) == 1
    assert rows[0].product_id == 12
    assert rows[0].sales_date == date(2026, 11, 12)
    assert rows[0].quantity == Decimal("0.000")
    assert rows[0].external_reference == "POS-12-20261112"


@pytest.mark.parametrize(
    ("csv_text", "message"),
    [
        ("", "empty"),
        ("product_id,quantity\n12,2\n", "Missing required"),
        (HEADER + "x,2026-11-12,2,REF-1\n", "product_id"),
        (HEADER + "12,12-11-2026,2,REF-1\n", "sales_date"),
        (HEADER + "12,2026-11-12,-1,REF-1\n", "quantity"),
        (HEADER + "12,2026-11-12,NaN,REF-1\n", "quantity"),
        (HEADER + "12,2026-11-12,1.2345,REF-1\n", "quantity"),
        (HEADER + "12,2026-11-12,1,\n", "external_reference"),
    ],
)
def test_parse_daily_sales_csv_rejects_invalid_rows(csv_text, message):
    with pytest.raises(ValueError, match=message):
        parse_daily_sales_csv(csv_text.encode("utf-8"))


def test_parse_daily_sales_csv_rejects_duplicate_references_in_same_file():
    payload = (
        HEADER
        + "12,2026-11-12,2,POS-REF-1\n"
        + "13,2026-11-12,4,POS-REF-1\n"
    ).encode("utf-8")
    with pytest.raises(ValueError, match="Duplicate external_reference"):
        parse_daily_sales_csv(payload)


def test_parse_daily_sales_csv_enforces_row_limit():
    rows = "".join(
        f"12,2026-11-12,1,REF-{index}\n"
        for index in range(MAX_IMPORT_ROWS + 1)
    )
    with pytest.raises(ValueError, match="maximum"):
        parse_daily_sales_csv((HEADER + rows).encode("utf-8"))


@pytest.mark.parametrize(
    ("csv_text", "message"),
    [
        (HEADER + "9223372036854775808,2026-11-12,1,REF-1\n", "product_id"),
        (HEADER + "12,2026-W46-1,1,REF-1\n", "sales_date"),
        (HEADER + "12,2026-11-12,1,REF-\x01-1\\n", "external_reference"),
    ],
)
def test_parse_daily_sales_csv_rejects_nonportable_or_out_of_range_values(csv_text, message):
    with pytest.raises(ValueError, match=message):
        parse_daily_sales_csv(csv_text.encode("utf-8"))


def test_parse_daily_sales_csv_rejects_nul_bytes():
    with pytest.raises(ValueError, match="NUL"):
        parse_daily_sales_csv((HEADER + "12,2026-11-12,1,REF-1\n").encode("utf-8") + b"\x00")
