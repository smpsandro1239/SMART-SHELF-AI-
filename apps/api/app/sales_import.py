"""Strict CSV parsing for daily sales imports."""
import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


MAX_IMPORT_ROWS = 5000
REQUIRED_COLUMNS = ("product_id", "sales_date", "quantity", "external_reference")


@dataclass(frozen=True)
class ParsedSalesRow:
    product_id: int
    sales_date: date
    quantity: Decimal
    external_reference: str


def parse_daily_sales_csv(payload: bytes) -> list[ParsedSalesRow]:
    """Parse a bounded UTF-8 CSV; reject malformed rows instead of silently skipping them."""
    if not payload:
        raise ValueError("CSV file is empty")
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must use UTF-8 encoding") from exc

    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    if reader.fieldnames is None:
        raise ValueError("CSV header row is required")
    headers = [header.strip() if header else "" for header in reader.fieldnames]
    if len(headers) != len(set(headers)):
        raise ValueError("CSV contains duplicate column names")
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise ValueError(f"Missing required CSV columns: {', '.join(missing)}")

    rows: list[ParsedSalesRow] = []
    seen_references: set[str] = set()
    for line_number, raw in enumerate(reader, start=2):
        if None in raw:
            raise ValueError(f"Too many columns at CSV line {line_number}")
        if not raw or all(value is None or not value.strip() for value in raw.values()):
            continue
        if len(rows) >= MAX_IMPORT_ROWS:
            raise ValueError(f"CSV exceeds the maximum of {MAX_IMPORT_ROWS} data rows")
        row = {(key.strip() if key else ""): (value.strip() if value else "") for key, value in raw.items()}
        try:
            product_id = int(row["product_id"])
            if product_id <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid product_id at CSV line {line_number}") from exc
        try:
            sales_date = date.fromisoformat(row["sales_date"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid sales_date at CSV line {line_number}; expected YYYY-MM-DD") from exc
        try:
            quantity = Decimal(row["quantity"])
            if not quantity.is_finite() or quantity < 0 or quantity > Decimal("999999999.999"):
                raise InvalidOperation
            rounded_quantity = quantity.quantize(Decimal("0.001"))
            if rounded_quantity != quantity:
                raise InvalidOperation
            quantity = rounded_quantity
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid quantity at CSV line {line_number}") from exc
        reference = row["external_reference"]
        if not reference or len(reference) > 120:
            raise ValueError(f"Invalid external_reference at CSV line {line_number}")
        if reference in seen_references:
            raise ValueError(f"Duplicate external_reference in CSV at line {line_number}: {reference}")
        seen_references.add(reference)
        rows.append(ParsedSalesRow(
            product_id=product_id,
            sales_date=sales_date,
            quantity=quantity,
            external_reference=reference,
        ))

    if not rows:
        raise ValueError("CSV contains no sales rows")
    return rows
