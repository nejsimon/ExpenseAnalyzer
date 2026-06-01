import hashlib
import sqlite3
from datetime import date, timedelta

from expense_analyzer.db import fetch_accounts, fetch_transactions, init_db, insert_transaction
from expense_analyzer.recurring import build_patterns
from expense_analyzer.stats import compute_stats
from unittest.mock import patch


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _add_tx(conn, desc, account, amount, booking_date):
    d = booking_date.isoformat()
    m = d[:7]
    h = hashlib.sha256(f"{d}|{desc}|{desc}|{amount}|{account}".encode()).hexdigest()
    insert_transaction(conn, {
        "row_number": 1, "clearing": "", "account": account, "product": "",
        "currency": "SEK", "booking_date": d, "transaction_date": d,
        "value_date": d, "reference": desc, "description": desc,
        "amount": amount, "balance": 0.0, "import_hash": h,
        "analysis_month": m,
    })


# --- fetch_accounts ---

def test_fetch_accounts_lists_all():
    conn = _make_conn()
    _add_tx(conn, "M", "ACC1", -100.0, date(2026, 1, 15))
    _add_tx(conn, "M", "ACC1", -100.0, date(2026, 2, 15))
    _add_tx(conn, "M", "ACC2", -200.0, date(2026, 1, 15))
    accts = fetch_accounts(conn)
    assert len(accts) == 2
    acct_map = dict(accts)
    assert acct_map["ACC1"] == 2
    assert acct_map["ACC2"] == 1


def test_fetch_accounts_empty():
    conn = _make_conn()
    assert fetch_accounts(conn) == []


# --- fetch_transactions account filter ---

def test_fetch_transactions_filters_by_account():
    conn = _make_conn()
    _add_tx(conn, "M", "ACC1", -100.0, date(2026, 1, 15))
    _add_tx(conn, "M", "ACC2", -200.0, date(2026, 1, 15))
    rows = fetch_transactions(conn, outgoing_only=True, account="ACC1")
    assert len(rows) == 1
    assert rows[0]["account"] == "ACC1"


def test_fetch_transactions_no_filter_returns_all():
    conn = _make_conn()
    _add_tx(conn, "M", "ACC1", -100.0, date(2026, 1, 15))
    _add_tx(conn, "M", "ACC2", -200.0, date(2026, 1, 15))
    rows = fetch_transactions(conn, outgoing_only=True)
    assert len(rows) == 2


# --- dedup respects account ---

def test_same_transaction_different_accounts_both_inserted():
    conn = _make_conn()
    # Same date/desc/amount, different accounts — should both be stored
    _add_tx(conn, "Sub", "ACC1", -100.0, date(2026, 3, 15))
    _add_tx(conn, "Sub", "ACC2", -100.0, date(2026, 3, 15))
    rows = fetch_transactions(conn, outgoing_only=True)
    assert len(rows) == 2


def test_same_transaction_same_account_deduplicated():
    conn = _make_conn()
    _add_tx(conn, "Sub", "ACC1", -100.0, date(2026, 3, 15))
    # Second insert — same hash → ignored
    result = insert_transaction(conn, {
        "row_number": 2, "clearing": "", "account": "ACC1", "product": "",
        "currency": "SEK", "booking_date": "2026-03-15", "transaction_date": "2026-03-15",
        "value_date": "2026-03-15", "reference": "Sub", "description": "Sub",
        "amount": -100.0, "balance": 0.0,
        "import_hash": hashlib.sha256(
            f"2026-03-15|Sub|Sub|-100.0|ACC1".encode()
        ).hexdigest(),
        "analysis_month": "2026-03",
    })
    assert result is False
    rows = fetch_transactions(conn, outgoing_only=True)
    assert len(rows) == 1


# --- build_patterns account filter ---

def test_build_patterns_filters_by_account():
    conn = _make_conn()
    base = date(2025, 1, 15)
    for i in range(6):
        _add_tx(conn, "Spotify", "ACC1", -119.0, base + timedelta(days=30 * i))
        _add_tx(conn, "Netflix", "ACC2", -99.0,  base + timedelta(days=30 * i))

    p1, _ = build_patterns(conn, reference_date=date(2025, 8, 1), account="ACC1")
    p2, _ = build_patterns(conn, reference_date=date(2025, 8, 1), account="ACC2")

    assert all(p.description == "Spotify" for p in p1)
    assert all(p.description == "Netflix" for p in p2)


# --- compute_stats account filter ---

def test_compute_stats_filters_by_account():
    conn = _make_conn()
    _add_tx(conn, "M", "ACC1", -300.0, date(2024, 6, 15))
    _add_tx(conn, "M", "ACC2", -900.0, date(2024, 6, 15))

    with patch("expense_analyzer.stats.date") as mock_date:
        mock_date.today.return_value = date(2025, 1, 1)
        s1 = compute_stats(conn, account="ACC1")
        s2 = compute_stats(conn, account="ACC2")

    assert s1[0].actual_expense == pytest.approx(300.0)
    assert s2[0].actual_expense == pytest.approx(900.0)


import pytest
