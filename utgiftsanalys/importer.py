import csv
import hashlib
import sqlite3
import sys
from datetime import date
from pathlib import Path

import chardet

from .adapters import AmbiguousAdapterError, CsvAdapter, detect_adapter
from .calendar_utils import get_analysis_month
from .db import insert_transaction


def detect_encoding(path: str) -> str:
    with open(path, "rb") as f:
        raw = f.read(65536)
    # UTF-8 BOM → use utf-8-sig so Python strips the BOM automatically
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    result = chardet.detect(raw)
    if result["encoding"] and result["confidence"] >= 0.7:
        enc = result["encoding"].lower()
        # Normalize chardet's utf-8 result to utf-8-sig to handle any stray BOM
        return "utf-8-sig" if enc in ("utf-8", "ascii") else result["encoding"]
    # Fallback: try windows-1252 then utf-8
    for enc in ("windows-1252", "utf-8"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def _compute_hash(booking_date: str, reference: str, description: str, amount: str, account: str) -> str:
    key = f"{booking_date}|{reference}|{description}|{amount}|{account}"
    return hashlib.sha256(key.encode()).hexdigest()


def _parse_amount(value: str, decimal_sep: str = ".") -> float:
    if decimal_sep == ",":
        clean = value.replace(" ", "").replace(".", "").replace(",", ".")
    else:
        clean = value.replace(",", "").replace(" ", "")
    return float(clean)


def _normalize_row(raw: dict, adapter: CsvAdapter) -> dict:
    tx: dict = {}
    for csv_col, internal in adapter.column_map.items():
        tx[internal] = raw.get(csv_col, "").strip()

    tx["row_number"] = int(tx["row_number"]) if tx["row_number"] else None
    tx["amount"] = _parse_amount(tx["amount"], adapter.decimal_sep) if tx["amount"] else 0.0
    tx["balance"] = _parse_amount(tx["balance"], adapter.decimal_sep) if tx["balance"] else 0.0

    booking = date.fromisoformat(tx["booking_date"])
    tx["analysis_month"] = get_analysis_month(booking)
    tx["import_hash"] = _compute_hash(
        tx["booking_date"], tx["reference"], tx["description"], str(tx["amount"]), tx["account"]
    )
    return tx


def add_months(ym: str, n: int) -> str:
    """Return YYYY-MM offset by n months (n may be negative)."""
    year, month = int(ym[:4]), int(ym[5:7])
    month += n
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    return f"{year}-{month:02d}"


def detect_holes(batch: list[dict]) -> list[str]:
    """Return warning strings for suspected missing months in the batch."""
    warnings: list[str] = []

    all_months = sorted({tx["analysis_month"] for tx in batch})
    if len(all_months) < 2:
        return warnings

    # Check 1 — sequence gaps
    gaps = []
    for i in range(len(all_months) - 1):
        expected = add_months(all_months[i], 1)
        cursor = expected
        while cursor != all_months[i + 1]:
            gaps.append(cursor)
            cursor = add_months(cursor, 1)
    if gaps:
        warnings.append(
            f"Warning: month(s) {', '.join(gaps)} appear to be missing from the import "
            f"(no transactions found)."
        )

    # Check 2 — merchant disappearance (run for outgoing and incoming separately)
    for sign, label in [(-1, "outgoing"), (1, "incoming")]:
        groups: dict[tuple[str, str], set[str]] = {}
        for tx in batch:
            if (tx["amount"] * sign) > 0:
                key = (tx["reference"], tx["description"])
                groups.setdefault(key, set()).add(tx["analysis_month"])

        for (ref, desc), months in groups.items():
            for m in sorted(months):
                middle = add_months(m, 1)
                after = add_months(m, 2)
                if after in months and middle not in months:
                    warnings.append(
                        f"Warning: '{desc}' ({label}) present in {m} and {after} "
                        f"but missing in {middle} — possible gap."
                    )

    return warnings


def import_file(
    path: str,
    conn: sqlite3.Connection,
    adapter: CsvAdapter | None = None,
) -> tuple[int, int, list[str]]:
    """Parse CSV and insert rows. Returns (inserted, skipped, warnings).

    Raises AmbiguousAdapterError if multiple adapters match and none is specified.
    Raises ValueError if no adapter matches.
    """
    encoding = detect_encoding(path)
    batch: list[dict] = []
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.DictReader(f, delimiter=adapter.delimiter if adapter else ",")
        if adapter is None:
            headers = list(reader.fieldnames or [])
            result = detect_adapter(headers)
            if isinstance(result, list):
                raise AmbiguousAdapterError(result)
            adapter = result
            # Re-open with correct delimiter if it differs from the default
            if adapter.delimiter != ",":
                f.seek(0)
                reader = csv.DictReader(f, delimiter=adapter.delimiter)
        for raw in reader:
            batch.append(_normalize_row(raw, adapter))

    warnings = detect_holes(batch)
    for w in warnings:
        print(w, file=sys.stderr)

    inserted = skipped = 0
    for tx in batch:
        if insert_transaction(conn, tx):
            inserted += 1
        else:
            skipped += 1
    conn.commit()
    return inserted, skipped, warnings
