import csv
import io
import sqlite3
import tempfile
from pathlib import Path

import pytest

from expense_analyzer.adapters import (
    ADAPTERS,
    AmbiguousAdapterError,
    CsvAdapter,
    SwedBankAdapter,
    detect_adapter,
)
from expense_analyzer.importer import _parse_amount, import_file
from expense_analyzer.db import init_db, get_connection


# --- detect_adapter ---

def test_detect_swedbank_exact_match():
    headers = ["Radnummer", "Clearingnummer", "Kontonummer", "Produkt", "Valuta",
               "Bokföringsdag", "Transaktionsdag", "Valutadag", "Referens",
               "Beskrivning", "Belopp", "Bokfört saldo"]
    result = detect_adapter(headers)
    assert result is SwedBankAdapter


def test_detect_strips_bom_from_headers():
    # BOM on first header should still match
    headers = ["﻿Bokföringsdag", "Beskrivning", "Belopp", "Kontonummer"]
    result = detect_adapter(headers)
    assert result is SwedBankAdapter


def test_detect_strips_whitespace_from_headers():
    headers = ["  Bokföringsdag  ", " Beskrivning", "Belopp", "Kontonummer"]
    result = detect_adapter(headers)
    assert result is SwedBankAdapter


def test_detect_no_match_raises():
    headers = ["Date", "Description", "Amount"]
    with pytest.raises(ValueError, match="No adapter matched"):
        detect_adapter(headers)


def test_detect_no_match_error_lists_headers():
    headers = ["Date", "Amount"]
    with pytest.raises(ValueError) as exc_info:
        detect_adapter(headers)
    assert "Date" in str(exc_info.value)


def test_detect_ambiguous_returns_list():
    a1 = CsvAdapter("bank1", ["ColA"], {"ColA": "description"})
    a2 = CsvAdapter("bank2", ["ColA"], {"ColA": "description"})
    result = detect_adapter(["ColA"], adapters=[a1, a2])
    assert isinstance(result, list)
    assert len(result) == 2


def test_detect_single_match_from_multiple_adapters():
    a1 = CsvAdapter("bank1", ["ColA"], {"ColA": "description"})
    a2 = CsvAdapter("bank2", ["ColB"], {"ColB": "description"})
    result = detect_adapter(["ColA"], adapters=[a1, a2])
    assert result is a1


# --- _parse_amount ---

def test_parse_amount_period_decimal():
    assert _parse_amount("1234.56") == pytest.approx(1234.56)


def test_parse_amount_space_thousands():
    assert _parse_amount("1 234.56") == pytest.approx(1234.56)


def test_parse_amount_comma_decimal():
    assert _parse_amount("1234,56", decimal_sep=",") == pytest.approx(1234.56)


def test_parse_amount_comma_decimal_with_period_thousands():
    assert _parse_amount("1.234,56", decimal_sep=",") == pytest.approx(1234.56)


def test_parse_amount_negative():
    assert _parse_amount("-500.00") == pytest.approx(-500.0)


# --- import_file with adapter ---

def _make_swedbank_csv(rows: list[dict]) -> str:
    headers = ["Radnummer", "Clearingnummer", "Kontonummer", "Produkt", "Valuta",
               "Bokföringsdag", "Transaktionsdag", "Valutadag", "Referens",
               "Beskrivning", "Belopp", "Bokfört saldo"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=headers)
    w.writeheader()
    for row in rows:
        w.writerow(row)
    return buf.getvalue()


def _default_row(**overrides):
    row = {
        "Radnummer": "1", "Clearingnummer": "8000", "Kontonummer": "12345678",
        "Produkt": "Privatkonto", "Valuta": "SEK",
        "Bokföringsdag": "2026-02-15", "Transaktionsdag": "2026-02-15",
        "Valutadag": "2026-02-15", "Referens": "REF1",
        "Beskrivning": "Spotify", "Belopp": "-119.00", "Bokfört saldo": "5000.00",
    }
    row.update(overrides)
    return row


def _conn_with_csv(content: str, adapter=None):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(content)
        path = f.name
    inserted, skipped, _ = import_file(path, conn, adapter=adapter)
    return conn, inserted, skipped


def test_import_auto_detects_swedbank():
    content = _make_swedbank_csv([_default_row()])
    _, inserted, _ = _conn_with_csv(content)
    assert inserted == 1


def test_import_with_explicit_adapter():
    content = _make_swedbank_csv([_default_row()])
    _, inserted, _ = _conn_with_csv(content, adapter=SwedBankAdapter)
    assert inserted == 1


def test_import_unknown_headers_raises():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Description", "Amount"])
    w.writerow(["2026-02-15", "Coffee", "-50"])
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(buf.getvalue())
        path = f.name
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    with pytest.raises(ValueError, match="No adapter matched"):
        import_file(path, conn)


def test_ambiguous_adapter_error_carries_candidates():
    a1 = CsvAdapter("bank1", ["ColA"], {"ColA": "description"})
    a2 = CsvAdapter("bank2", ["ColA"], {"ColA": "description"})
    exc = AmbiguousAdapterError([a1, a2])
    assert exc.candidates == [a1, a2]
    assert "bank1" in str(exc)
    assert "bank2" in str(exc)


def test_detect_adapter_ambiguous_path_raises_ambiguous_error_in_importer(monkeypatch):
    a1 = CsvAdapter("bank1", ["Bokföringsdag", "Beskrivning", "Belopp", "Kontonummer"],
                    SwedBankAdapter.column_map)
    a2 = CsvAdapter("bank2", ["Bokföringsdag", "Beskrivning", "Belopp", "Kontonummer"],
                    SwedBankAdapter.column_map)
    import expense_analyzer.importer as imp_mod
    import expense_analyzer.adapters as adp_mod
    monkeypatch.setattr(adp_mod, "ADAPTERS", [a1, a2])

    content = _make_swedbank_csv([_default_row()])
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(content)
        path = f.name
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    with pytest.raises(AmbiguousAdapterError) as exc_info:
        import_file(path, conn)
    assert len(exc_info.value.candidates) == 2


# --- adapters registry ---

def test_adapters_list_not_empty():
    assert len(ADAPTERS) >= 1


def test_swedbank_in_adapters():
    assert any(a.name == "swedbank" for a in ADAPTERS)
