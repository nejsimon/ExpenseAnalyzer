import sqlite3
from datetime import date, timedelta

import pytest

from utgiftsanalys.db import add_group_member, init_db, insert_group, insert_transaction
from utgiftsanalys.recurring import build_patterns


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _add_tx(conn, desc, ref, amount, booking_date, analysis_month=None):
    d = booking_date.isoformat()
    m = analysis_month or d[:7]
    import hashlib
    h = hashlib.sha256(f"{d}|{ref}|{desc}|{amount}".encode()).hexdigest()
    insert_transaction(conn, {
        "row_number": 1, "clearing": "", "account": "", "product": "",
        "currency": "SEK", "booking_date": d, "transaction_date": d,
        "value_date": d, "reference": ref, "description": desc,
        "amount": amount, "balance": 0.0, "import_hash": h,
        "analysis_month": m,
    })


def test_monthly_fixed_detected():
    conn = _make_conn()
    base = date(2025, 1, 15)
    for i in range(6):
        _add_tx(conn, "Spotify", "Spotify", -119.0, base + timedelta(days=30 * i))
    patterns, one_offs = build_patterns(conn, reference_date=date(2025, 7, 1))
    assert len(patterns) == 1
    p = patterns[0]
    assert p.cadence == "monthly"
    assert p.amount_type == "fixed"
    assert abs(p.fixed_amount - 119.0) < 0.1
    assert p.status == "active"


def test_variable_amount_detected():
    conn = _make_conn()
    base = date(2025, 1, 10)
    amounts = [-400, -600, -820, -450, -700]
    for i, a in enumerate(amounts):
        _add_tx(conn, "El", "El", a, base + timedelta(days=30 * i))
    patterns, _ = build_patterns(conn, reference_date=date(2025, 6, 1))
    assert len(patterns) == 1
    p = patterns[0]
    assert p.amount_type == "variable"
    assert p.min_amount == pytest.approx(400.0)
    assert p.max_amount == pytest.approx(820.0)


def test_canceled_when_overdue():
    conn = _make_conn()
    base = date(2024, 1, 15)
    for i in range(4):
        _add_tx(conn, "Gym", "Gym", -300.0, base + timedelta(days=30 * i))
    # reference_date is 3 months after last occurrence → should be canceled
    patterns, _ = build_patterns(conn, reference_date=date(2024, 7, 1))
    assert len(patterns) == 1
    assert patterns[0].status == "canceled"
    assert patterns[0].end_date is not None


def test_single_occurrence_is_one_off():
    conn = _make_conn()
    _add_tx(conn, "IKEA", "IKEA", -1500.0, date(2026, 3, 5))
    patterns, one_offs = build_patterns(conn, reference_date=date(2026, 4, 1))
    assert len(patterns) == 0
    assert len(one_offs) == 1


def test_quarterly_detected():
    conn = _make_conn()
    base = date(2024, 1, 10)
    for i in range(4):
        _add_tx(conn, "Kvartals", "Kvartals", -500.0, base + timedelta(days=91 * i))
    patterns, _ = build_patterns(conn, reference_date=date(2025, 2, 1))
    assert len(patterns) == 1
    assert patterns[0].cadence == "quarterly"


def test_yearly_detected():
    conn = _make_conn()
    for year in [2023, 2024, 2025]:
        _add_tx(conn, "Försäkring", "Försäkring", -2400.0, date(year, 3, 10))
    patterns, _ = build_patterns(conn, reference_date=date(2025, 6, 1))
    assert len(patterns) == 1
    assert patterns[0].cadence == "yearly"


def test_price_increase_updates_fixed_amount():
    conn = _make_conn()
    base = date(2025, 1, 15)
    # 3 months at old price, then 3 months at new price
    for i in range(3):
        _add_tx(conn, "Netflix", "Netflix", -99.0, base + timedelta(days=30 * i))
    for i in range(3):
        _add_tx(conn, "Netflix", "Netflix", -129.0, base + timedelta(days=30 * (i + 3)))
    patterns, _ = build_patterns(conn, reference_date=date(2025, 8, 1))
    assert len(patterns) == 1
    p = patterns[0]
    assert p.amount_type == "fixed"
    assert abs(p.fixed_amount - 129.0) < 0.1


def test_inconsistent_gaps_are_one_offs():
    conn = _make_conn()
    # Gaps: 31 days, then 120 days — too inconsistent for any cadence
    _add_tx(conn, "Misc", "Misc", -200.0, date(2025, 1, 1))
    _add_tx(conn, "Misc", "Misc", -200.0, date(2025, 2, 1))
    _add_tx(conn, "Misc", "Misc", -200.0, date(2025, 6, 1))
    patterns, one_offs = build_patterns(conn, reference_date=date(2025, 7, 1))
    assert len(patterns) == 0
    assert len(one_offs) == 3


def test_start_date_is_first_occurrence():
    conn = _make_conn()
    base = date(2025, 3, 10)
    for i in range(4):
        _add_tx(conn, "Sub", "Sub", -49.0, base + timedelta(days=30 * i))
    patterns, _ = build_patterns(conn, reference_date=date(2025, 8, 1))
    assert patterns[0].start_date == base


def test_multiple_line_items_per_month_detected_as_monthly():
    """Multiple transactions on the same date (e.g. Lf Uppsala) must not break detection."""
    conn = _make_conn()
    base = date(2025, 1, 2)
    for month in range(6):
        booking = date(2025, 1 + month, 2)
        for amount in [-182.0, -186.0, -195.0]:
            _add_tx(conn, "Lf Uppsala", "Lf Uppsala", amount, booking)
    patterns, one_offs = build_patterns(conn, reference_date=date(2025, 8, 1))
    assert len(patterns) == 1
    assert patterns[0].cadence == "monthly"
    assert len(one_offs) == 0


def test_quarterly_with_noisy_early_occurrences():
    """Quarterly pattern with some consecutive-month noise (e.g. U A VA) must be detected."""
    conn = _make_conn()
    # Mostly quarterly (3-month) gaps but a few 1-month gaps mixed in
    months_and_ams = [
        (date(2024, 4, 2),  "2024-03"),
        (date(2024, 4, 30), "2024-04"),
        (date(2024, 9, 2),  "2024-08"),
        (date(2024, 12, 2), "2024-11"),
        (date(2025, 3, 3),  "2025-02"),
        (date(2025, 6, 2),  "2025-05"),
        (date(2025, 9, 1),  "2025-08"),
    ]
    for booking, am in months_and_ams:
        _add_tx(conn, "U A VA", "U A VA", -2800.0, booking, analysis_month=am)
    patterns, one_offs = build_patterns(conn, reference_date=date(2025, 10, 1))
    assert len(patterns) == 1
    assert patterns[0].cadence == "quarterly"
    assert len(one_offs) == 0


def test_deposits_excluded():
    conn = _make_conn()
    base = date(2025, 1, 15)
    for i in range(6):
        _add_tx(conn, "Salary", "Salary", +25000.0, base + timedelta(days=30 * i))
    patterns, one_offs = build_patterns(conn, reference_date=date(2025, 7, 1))
    assert len(patterns) == 0
    assert len(one_offs) == 0


def test_grouped_false_returns_individual_members():
    """With grouped=False, group member merchants appear as individual patterns."""
    conn = _make_conn()
    insert_group(conn, "Phone bundle", "expenses", "#ff0000")
    add_group_member(conn, "Phone bundle", "TeliaRef", "Telia")
    add_group_member(conn, "Phone bundle", "ComviqRef", "Comviq")
    base = date(2025, 1, 15)
    for i in range(4):
        _add_tx(conn, "Telia", "TeliaRef", -199.0, base + timedelta(days=30 * i))
        _add_tx(conn, "Comviq", "ComviqRef", -99.0, base + timedelta(days=30 * i))
    patterns, _ = build_patterns(conn, reference_date=date(2025, 6, 1), grouped=False)
    descs = {p.description for p in patterns}
    assert "Telia" in descs
    assert "Comviq" in descs
    assert "Phone bundle" not in descs


def test_grouped_true_returns_group_pattern():
    """With grouped=True (default), group members are aggregated into a single pattern."""
    conn = _make_conn()
    insert_group(conn, "Phone bundle", "expenses", "#ff0000")
    add_group_member(conn, "Phone bundle", "TeliaRef", "Telia")
    add_group_member(conn, "Phone bundle", "ComviqRef", "Comviq")
    base = date(2025, 1, 15)
    for i in range(4):
        _add_tx(conn, "Telia", "TeliaRef", -199.0, base + timedelta(days=30 * i))
        _add_tx(conn, "Comviq", "ComviqRef", -99.0, base + timedelta(days=30 * i))
    patterns, _ = build_patterns(conn, reference_date=date(2025, 6, 1), grouped=True)
    descs = {p.description for p in patterns}
    assert "Phone bundle" in descs
    assert "Telia" not in descs
    assert "Comviq" not in descs
