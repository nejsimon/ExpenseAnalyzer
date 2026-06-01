import sqlite3
from datetime import date, timedelta

import pytest

from utgiftsanalys.db import init_db, insert_transaction
from utgiftsanalys.stats import compute_stats


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _add_tx(conn, amount, analysis_month, desc="M", ref="M"):
    import hashlib
    d = analysis_month + "-15"
    h = hashlib.sha256(f"{d}|{ref}|{desc}|{amount}|{analysis_month}".encode()).hexdigest()
    insert_transaction(conn, {
        "row_number": 1, "clearing": "", "account": "", "product": "",
        "currency": "SEK", "booking_date": d, "transaction_date": d,
        "value_date": d, "reference": ref, "description": desc,
        "amount": amount, "balance": 0.0, "import_hash": h,
        "analysis_month": analysis_month,
    })


def test_empty_db_returns_no_stats():
    conn = _make_conn()
    assert compute_stats(conn) == []


def test_single_past_year():
    conn = _make_conn()
    for m in range(1, 13):
        _add_tx(conn, -400.0, f"2024-{m:02d}")
    stats = compute_stats(conn, reference_date=date(2025, 6, 1))

    assert len(stats) == 1
    s = stats[0]
    assert s.year == 2024
    assert s.actual_expense == pytest.approx(4800.0)
    assert s.actual_months == 12
    assert s.avg_expense == pytest.approx(400.0)
    assert s.predicted_expense_remaining is None   # past year → no prediction


def test_current_year_has_prediction():
    conn = _make_conn()
    # 4 months of data — need active recurring pattern for prediction
    base = date(2026, 1, 15)
    for i in range(4):
        d = base + timedelta(days=30 * i)
        m = f"{d.year}-{d.month:02d}"
        import hashlib
        h = hashlib.sha256(f"{d.isoformat()}|Sub|Sub|-200.0".encode()).hexdigest()
        insert_transaction(conn, {
            "row_number": 1, "clearing": "", "account": "", "product": "",
            "currency": "SEK", "booking_date": d.isoformat(),
            "transaction_date": d.isoformat(), "value_date": d.isoformat(),
            "reference": "Sub", "description": "Sub",
            "amount": -200.0, "balance": 0.0, "import_hash": h,
            "analysis_month": m,
        })

    stats = compute_stats(conn, reference_date=date(2026, 5, 1))

    assert len(stats) == 1
    s = stats[0]
    assert s.year == 2026
    assert s.predicted_expense_remaining is not None
    assert s.predicted_expense_remaining > 0


def test_income_tracked_separately():
    conn = _make_conn()
    _add_tx(conn, -300.0, "2025-01")
    _add_tx(conn, 25000.0, "2025-01")
    stats = compute_stats(conn, reference_date=date(2026, 1, 1))

    assert stats[0].actual_expense == pytest.approx(300.0)
    assert stats[0].actual_income == pytest.approx(25000.0)


def test_multiple_years():
    conn = _make_conn()
    _add_tx(conn, -500.0, "2024-06")
    _add_tx(conn, -600.0, "2025-06")
    stats = compute_stats(conn, reference_date=date(2026, 1, 1))

    years = [s.year for s in stats]
    assert 2024 in years and 2025 in years


def test_avg_expense_correct():
    conn = _make_conn()
    _add_tx(conn, -300.0, "2024-01")
    _add_tx(conn, -500.0, "2024-02")
    stats = compute_stats(conn, reference_date=date(2025, 1, 1))

    s = stats[0]
    assert s.actual_months == 2
    assert s.avg_expense == pytest.approx(400.0)   # (300 + 500) / 2
