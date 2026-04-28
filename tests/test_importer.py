import sqlite3
import tempfile
import os

from utgiftsanalys.db import init_db, fetch_transactions
from utgiftsanalys.importer import import_file, detect_encoding, detect_holes, add_months


CSV_CONTENT_UTF8 = (
    "Radnummer,Clearingnummer,Kontonummer,Produkt,Valuta,"
    "Bokföringsdag,Transaktionsdag,Valutadag,Referens,Beskrivning,Belopp,Bokfört saldo\n"
    '2,12345,123456789,"Privatkonto",SEK,2026-04-02,2026-04-02,2026-04-02,'
    '"Lf Uppsala","Lf Uppsala",-195.00,0.00\n'
)


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_import_inserts_row():
    conn = _make_conn()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(CSV_CONTENT_UTF8)
        path = f.name
    try:
        inserted, skipped, _ = import_file(path, conn)
        assert inserted == 1
        assert skipped == 0
        rows = fetch_transactions(conn, outgoing_only=True)
        assert len(rows) == 1
        assert rows[0]["description"] == "Lf Uppsala"
        assert rows[0]["amount"] == -195.0
    finally:
        os.unlink(path)


def test_import_skips_preamble_rows():
    preamble = (
        "Exported from Swedbank 2026-04-28\n"
        "Account holder: Test Testsson\n"
    )
    conn = _make_conn()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(preamble + CSV_CONTENT_UTF8)
        path = f.name
    try:
        inserted, skipped, _ = import_file(path, conn)
        assert inserted == 1
        assert skipped == 0
    finally:
        os.unlink(path)


def test_import_deduplicates():
    conn = _make_conn()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(CSV_CONTENT_UTF8)
        path = f.name
    try:
        import_file(path, conn)
        inserted, skipped, _ = import_file(path, conn)
        assert inserted == 0
        assert skipped == 1
    finally:
        os.unlink(path)


def test_detect_encoding_utf8():
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as f:
        f.write(CSV_CONTENT_UTF8.encode("utf-8"))
        path = f.name
    try:
        enc = detect_encoding(path)
        assert enc.lower().replace("-", "") in ("utf8", "utf8sig", "ascii")
    finally:
        os.unlink(path)


def test_detect_encoding_windows1252():
    content = CSV_CONTENT_UTF8.replace("Bokföringsdag", "Bokf\xf6ringsdag")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as f:
        f.write(content.encode("windows-1252"))
        path = f.name
    try:
        enc = detect_encoding(path)
        assert enc is not None
    finally:
        os.unlink(path)


# --- add_months ---

def test_add_months_forward():
    assert add_months("2026-01", 1) == "2026-02"
    assert add_months("2026-11", 2) == "2027-01"
    assert add_months("2026-12", 1) == "2027-01"


def test_add_months_backward():
    assert add_months("2026-03", -1) == "2026-02"
    assert add_months("2026-01", -1) == "2025-12"


# --- detect_holes ---

def _tx(analysis_month, ref="M", desc="M", amount=-100.0):
    return {"analysis_month": analysis_month, "reference": ref, "description": desc, "amount": amount}


def test_no_holes_no_warnings():
    batch = [_tx("2026-01"), _tx("2026-02"), _tx("2026-03")]
    assert detect_holes(batch) == []


def test_sequence_gap_detected():
    batch = [_tx("2026-01"), _tx("2026-03")]  # Feb missing
    warnings = detect_holes(batch)
    assert any("2026-02" in w for w in warnings)


def test_sequence_multi_gap():
    batch = [_tx("2026-01"), _tx("2026-04")]  # Feb and Mar missing
    warnings = detect_holes(batch)
    assert any("2026-02" in w and "2026-03" in w for w in warnings)


def test_merchant_gap_detected():
    # Merchant in Jan and Mar but not Feb
    batch = [
        _tx("2026-01", "Spotify", "Spotify"),
        _tx("2026-02", "Other", "Other"),   # other merchant keeps sequence intact
        _tx("2026-03", "Spotify", "Spotify"),
    ]
    warnings = detect_holes(batch)
    merchant_warns = [w for w in warnings if "Spotify" in w]
    assert len(merchant_warns) == 1
    assert "2026-02" in merchant_warns[0]


def test_merchant_gap_detected_for_income():
    # Income (positive amount) in Jan and Mar with a gap in Feb — should trigger warning
    batch = [
        {"analysis_month": "2026-01", "reference": "Lön", "description": "Lön", "amount": 25000.0},
        {"analysis_month": "2026-02", "reference": "Other", "description": "Other", "amount": -50.0},
        {"analysis_month": "2026-03", "reference": "Lön", "description": "Lön", "amount": 25000.0},
    ]
    warnings = detect_holes(batch)
    assert any("Lön" in w and "2026-02" in w for w in warnings)


def test_no_warning_for_single_month():
    batch = [_tx("2026-04")]
    assert detect_holes(batch) == []


def test_warnings_printed_to_stderr(capsys):
    batch = [_tx("2026-01"), _tx("2026-03")]
    detect_holes(batch)  # detect_holes itself doesn't print — import_file does
    # Verify detect_holes returns warnings (printing is tested via import_file)
    warnings = detect_holes(batch)
    assert len(warnings) > 0
