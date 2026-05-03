import hashlib
import sqlite3
from datetime import date

import pytest

from utgiftsanalys.chart_data import monthly_actuals, monthly_group_breakdown
from utgiftsanalys.db import add_group_member, init_db, insert_group


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _add_tx(conn: sqlite3.Connection, desc: str, ref: str, amount: float, booking_date: date) -> None:
    d = booking_date.isoformat()
    h = hashlib.sha256(f"{d}|{ref}|{desc}|{amount}".encode()).hexdigest()
    conn.execute(
        """INSERT OR IGNORE INTO transactions
           (row_number, clearing, account, product, currency,
            booking_date, transaction_date, value_date,
            reference, description, amount, balance, import_hash, analysis_month)
           VALUES (1,'','','','SEK',?,?,?,?,?,?,0.0,?,?)""",
        (d, d, d, ref, desc, amount, h, d[:7]),
    )
    conn.commit()


def test_group_amounts_attributed_correctly():
    conn = _make_conn()
    insert_group(conn, "phone", "expenses", "#ff0000")
    add_group_member(conn, "phone", "Telia", "Telia")
    _add_tx(conn, "Telia", "Telia", -199.0, date(2025, 1, 5))
    _add_tx(conn, "Spotify", "Spotify", -119.0, date(2025, 1, 10))

    result = monthly_group_breakdown(conn, direction="expenses")
    assert len(result) == 2

    phone = next(r for r in result if r["group"] == "phone")
    assert phone["amount"] == pytest.approx(199.0)
    assert phone["color"] == "#ff0000"
    assert phone["month"] == "2025-01"

    other = next(r for r in result if r["group"] == "Other")
    assert other["amount"] == pytest.approx(119.0)
    assert other["color"] == "#888888"


def test_uncategorized_goes_to_other():
    conn = _make_conn()
    _add_tx(conn, "IKEA", "IKEA", -1500.0, date(2025, 3, 5))

    result = monthly_group_breakdown(conn, direction="expenses")
    assert len(result) == 1
    assert result[0]["group"] == "Other"
    assert result[0]["color"] == "#888888"
    assert result[0]["amount"] == pytest.approx(1500.0)


def test_no_transactions_for_group_produces_no_record():
    conn = _make_conn()
    insert_group(conn, "phone", "expenses", "#ff0000")
    add_group_member(conn, "phone", "Telia", "Telia")
    _add_tx(conn, "Spotify", "Spotify", -119.0, date(2025, 1, 5))

    result = monthly_group_breakdown(conn, direction="expenses")
    groups = {r["group"] for r in result}
    assert "phone" not in groups
    assert "Other" in groups


def test_multiple_months_each_get_own_records():
    conn = _make_conn()
    insert_group(conn, "phone", "expenses", "#ff0000")
    add_group_member(conn, "phone", "Telia", "Telia")
    _add_tx(conn, "Telia", "Telia", -199.0, date(2025, 1, 5))
    _add_tx(conn, "Telia", "Telia", -199.0, date(2025, 2, 5))

    result = monthly_group_breakdown(conn, direction="expenses")
    months = {r["month"] for r in result}
    assert "2025-01" in months
    assert "2025-02" in months
    assert all(r["amount"] == pytest.approx(199.0) for r in result)


def test_income_direction_uses_income_groups():
    conn = _make_conn()
    insert_group(conn, "salary", "income", "#00ff00")
    add_group_member(conn, "salary", "EmployerRef", "Employer")
    _add_tx(conn, "Employer", "EmployerRef", +30000.0, date(2025, 1, 25))

    result = monthly_group_breakdown(conn, direction="income")
    assert len(result) == 1
    assert result[0]["group"] == "salary"
    assert result[0]["amount"] == pytest.approx(30000.0)


# ── Offset member tests ───────────────────────────────────────────────────────


def test_offset_expense_hidden_from_expense_actuals():
    """An expense marked as offset should not appear in the expense total."""
    conn = _make_conn()
    insert_group(conn, "deposits", "income", "#0000ff")
    add_group_member(conn, "deposits", "XferIn", "Transfer In", is_offset=False)
    add_group_member(conn, "deposits", "XferBack", "Transfer Back", is_offset=True)
    _add_tx(conn, "Transfer In", "XferIn", +5000.0, date(2025, 4, 1))
    _add_tx(conn, "Transfer Back", "XferBack", -800.0, date(2025, 4, 28))
    _add_tx(conn, "Spotify", "Spotify", -119.0, date(2025, 4, 5))

    actuals = monthly_actuals(conn)
    april = next(r for r in actuals if r["month"] == "2025-04")
    # Transfer Back is an offset → excluded from expenses; only Spotify counts
    assert april["expenses"] == pytest.approx(119.0)
    assert april["income"] == pytest.approx(5000.0)


def test_offset_expense_hidden_from_expense_breakdown():
    """An offset expense must not appear in the expense group breakdown."""
    conn = _make_conn()
    insert_group(conn, "deposits", "income", "#0000ff")
    add_group_member(conn, "deposits", "XferBack", "Transfer Back", is_offset=True)
    _add_tx(conn, "Transfer Back", "XferBack", -800.0, date(2025, 4, 28))
    _add_tx(conn, "Spotify", "Spotify", -119.0, date(2025, 4, 5))

    result = monthly_group_breakdown(conn, direction="expenses")
    groups = {r["group"] for r in result}
    # Transfer Back belongs to an income group → must not appear in expense breakdown
    assert "deposits" not in groups
    assert "Other" in groups
    other = next(r for r in result if r["group"] == "Other")
    assert other["amount"] == pytest.approx(119.0)


def test_offset_expense_netted_in_income_group_breakdown():
    """Income group breakdown should show income minus offset expenses."""
    conn = _make_conn()
    insert_group(conn, "deposits", "income", "#0000ff")
    add_group_member(conn, "deposits", "XferIn", "Transfer In", is_offset=False)
    add_group_member(conn, "deposits", "XferBack", "Transfer Back", is_offset=True)
    _add_tx(conn, "Transfer In", "XferIn", +5000.0, date(2025, 4, 1))
    _add_tx(conn, "Transfer Back", "XferBack", -800.0, date(2025, 4, 28))

    result = monthly_group_breakdown(conn, direction="income")
    deposits = next(r for r in result if r["group"] == "deposits")
    assert deposits["amount"] == pytest.approx(5000.0 - 800.0)


def test_income_group_with_offset_builds_correct_pattern():
    """build_patterns for income should net offset expenses into the group amount."""
    conn = _make_conn()
    insert_group(conn, "deposits", "income", "#0000ff")
    add_group_member(conn, "deposits", "XferIn", "Transfer In", is_offset=False)
    add_group_member(conn, "deposits", "XferBack", "Transfer Back", is_offset=True)
    # Three months of transfer-in and transfer-back
    for month in range(3):
        _add_tx(conn, "Transfer In", "XferIn", +5000.0, date(2025, 1 + month, 1))
        _add_tx(conn, "Transfer Back", "XferBack", -800.0, date(2025, 1 + month, 28))

    from utgiftsanalys.recurring import build_patterns
    patterns, _ = build_patterns(conn, reference_date=date(2025, 5, 1), direction="income")
    assert len(patterns) == 1
    p = patterns[0]
    assert p.description == "deposits"
    assert p.amount_type == "fixed"
    assert p.fixed_amount == pytest.approx(4200.0)  # 5000 - 800


def test_offset_expense_excluded_from_expense_patterns():
    """A back-transfer added as offset should not appear as an individual expense pattern."""
    conn = _make_conn()
    insert_group(conn, "deposits", "income", "#0000ff")
    add_group_member(conn, "deposits", "XferBack", "Transfer Back", is_offset=True)
    for month in range(4):
        _add_tx(conn, "Transfer Back", "XferBack", -800.0, date(2025, 1 + month, 28))

    from utgiftsanalys.recurring import build_patterns
    exp_patterns, _ = build_patterns(conn, reference_date=date(2025, 6, 1), direction="expenses")
    descs = {p.description for p in exp_patterns}
    assert "Transfer Back" not in descs
