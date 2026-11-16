"""Strict CSV parsing for hourly sales and store traffic imports."""
import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_HOURLY_IMPORT_ROWS = 5000
MAX_HOURLY_IMPORT_BYTES = 5 * 1024 * 1024

@dataclass(frozen=True)
class ParsedHourlySalesRow:
    product_id: int
    business_date: date
    hour_of_day: int
    quantity: Decimal
    external_reference: str

@dataclass(frozen=True)
class ParsedHourlyTrafficRow:
    business_date: date
    hour_of_day: int
    customer_count: int
    external_reference: str

def _read_csv(payload: bytes, required_columns: tuple[str, ...]):
    if not payload:
        raise ValueError("CSV file is empty")
    if len(payload) > MAX_HOURLY_IMPORT_BYTES:
        raise ValueError(f"CSV exceeds the maximum file size of {MAX_HOURLY_IMPORT_BYTES} bytes")
    if b"\x00" in payload:
        raise ValueError("CSV must not contain NUL bytes")
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must use UTF-8 encoding") from exc
    reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
    try:
        fieldnames = reader.fieldnames
        raw_rows = list(reader)
    except csv.Error as exc:
        raise ValueError("CSV contains malformed quoting or syntax") from exc
    if fieldnames is None:
        raise ValueError("CSV header row is required")
    headers = [header.strip() if header else "" for header in fieldnames]
    if len(headers) != len(set(headers)):
        raise ValueError("CSV contains duplicate column names")
    missing = [column for column in required_columns if column not in headers]
    if missing:
        raise ValueError(f"Missing required CSV columns: {', '.join(missing)}")
    rows = []
    for line_number, raw in enumerate(raw_rows, start=2):
        if None in raw:
            raise ValueError(f"Too many columns at CSV line {line_number}")
        if not raw or all(value is None or not value.strip() for value in raw.values()):
            continue
        if len(rows) >= MAX_HOURLY_IMPORT_ROWS:
            raise ValueError(f"CSV exceeds the maximum of {MAX_HOURLY_IMPORT_ROWS} data rows")
        rows.append((line_number, {(key.strip() if key else ""): (value.strip() if value else "") for key, value in raw.items()}))
    if not rows:
        raise ValueError("CSV contains no data rows")
    return rows

def _hour(row: dict, line: int) -> int:
    try:
        if re.fullmatch(r"[0-9]+", row["hour_of_day"]) is None:
            raise ValueError
        value = int(row["hour_of_day"])
        if not 0 <= value <= 23:
            raise ValueError
        return value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid hour_of_day at CSV line {line}; expected 0-23") from exc

def _business_date(row: dict, line: int) -> date:
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row["business_date"]) is None:
            raise ValueError
        return date.fromisoformat(row["business_date"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid business_date at CSV line {line}; expected YYYY-MM-DD") from exc

def _reference(row: dict, line: int, seen: set[str]) -> str:
    value = row["external_reference"]
    if not value or len(value) > 120 or any(ord(char) < 32 or 127 <= ord(char) < 160 for char in value):
        raise ValueError(f"Invalid external_reference at CSV line {line}")
    if value in seen:
        raise ValueError(f"Duplicate external_reference in CSV at line {line}: {value}")
    seen.add(value)
    return value

def parse_hourly_sales_csv(payload: bytes) -> list[ParsedHourlySalesRow]:
    required = ("product_id", "business_date", "hour_of_day", "quantity", "external_reference")
    result, seen = [], set()
    for line, row in _read_csv(payload, required):
        try:
            if re.fullmatch(r"[0-9]+", row["product_id"]) is None:
                raise ValueError
            product_id = int(row["product_id"])
            if product_id <= 0 or product_id > 2**63 - 1:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid product_id at CSV line {line}") from exc
        try:
            quantity = Decimal(row["quantity"])
            if not quantity.is_finite() or quantity < 0 or quantity > Decimal("999999999.999") or quantity.quantize(Decimal("0.001")) != quantity:
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid quantity at CSV line {line}") from exc
        result.append(ParsedHourlySalesRow(product_id, _business_date(row, line), _hour(row, line), quantity, _reference(row, line, seen)))
    return result

def parse_hourly_traffic_csv(payload: bytes) -> list[ParsedHourlyTrafficRow]:
    required = ("business_date", "hour_of_day", "customer_count", "external_reference")
    result, seen = [], set()
    for line, row in _read_csv(payload, required):
        try:
            if re.fullmatch(r"[0-9]+", row["customer_count"]) is None:
                raise ValueError
            count = int(row["customer_count"])
            if not 0 <= count <= 2_000_000:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid customer_count at CSV line {line}") from exc
        result.append(ParsedHourlyTrafficRow(_business_date(row, line), _hour(row, line), count, _reference(row, line, seen)))
    return result
