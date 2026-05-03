import hashlib
import sqlite3
from datetime import date

import pytest

from utgiftsanalys.db import (
    add_group_member,
    delete_group,
    fetch_all_group_member_keys,
    fetch_group_members,
    fetch_groups,
    init_db,
    insert_group,
    remove_group_member,
    set_group_exclude,
    update_group_color,
)
from utgiftsanalys.recurring import build_patterns


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def _add_tx(conn, desc, ref, amount, booking_date, analysis_month=None):
    d = booking_date.isoformat()
    m = analysis_month or d[:7]
    h = hashlib.sha256(f"{d}|{ref}|{desc}|{amount}|acct".encode()).hexdigest()
    conn.execute(
        """INSERT OR IGNORE INTO transactions
           (row_number, clearing, account, product, currency,
            booking_date, transaction_date, value_date,
            reference, description, amount, balance, import_hash, analysis_month)
           VALUES (1,'','acct','','SEK',?,?,?,?,?,?,0.0,?,?)""",
        (d, d, d, ref, desc, amount, h, m),
    )
    conn.commit()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_insert_and_fetch_group():
    conn = _make_conn()
    gid = insert_group(conn, "phone", "expenses", "#3498db")
    assert isinstance(gid, int)
    groups = fetch_groups(conn)
    assert len(groups) == 1
    assert groups[0]["name"] == "phone"
    assert groups[0]["direction"] == "expenses"
    assert groups[0]["color"] == "#3498db"


def test_fetch_groups_filter_by_direction():
    conn = _make_conn()
    insert_group(conn, "phone", "expenses")
    insert_group(conn, "salary", "income")
    assert len(fetch_groups(conn, direction="expenses")) == 1
    assert len(fetch_groups(conn, direction="income")) == 1
    assert len(fetch_groups(conn)) == 2


def test_duplicate_group_name_raises():
    conn = _make_conn()
    insert_group(conn, "phone", "expenses")
    with pytest.raises(sqlite3.IntegrityError):
        insert_group(conn, "phone", "income")


def test_delete_group():
    conn = _make_conn()
    insert_group(conn, "phone", "expenses")
    assert delete_group(conn, "phone") is True
    assert fetch_groups(conn) == []
    assert delete_group(conn, "phone") is False


def test_add_and_fetch_members():
    conn = _make_conn()
    gid = insert_group(conn, "phone", "expenses")
    add_group_member(conn, "phone", "Telia", "Telia")
    add_group_member(conn, "phone", "Bredband", "Bredband")
    members = fetch_group_members(conn, gid)
    refs = {m["reference"] for m in members}
    assert refs == {"Telia", "Bredband"}


def test_member_in_two_groups_raises():
    conn = _make_conn()
    insert_group(conn, "phone", "expenses")
    insert_group(conn, "other", "expenses")
    add_group_member(conn, "phone", "Telia", "Telia")
    with pytest.raises(sqlite3.IntegrityError):
        add_group_member(conn, "other", "Telia", "Telia")


def test_remove_member():
    conn = _make_conn()
    gid = insert_group(conn, "phone", "expenses")
    add_group_member(conn, "phone", "Telia", "Telia")
    assert remove_group_member(conn, "phone", "Telia", "Telia") is True
    assert fetch_group_members(conn, gid) == []
    assert remove_group_member(conn, "phone", "Telia", "Telia") is False


def test_delete_group_cascades_to_members():
    conn = _make_conn()
    gid = insert_group(conn, "phone", "expenses")
    add_group_member(conn, "phone", "Telia", "Telia")
    delete_group(conn, "phone")
    assert conn.execute("SELECT * FROM group_members WHERE group_id = ?", (gid,)).fetchall() == []


# ── build_patterns with groups ────────────────────────────────────────────────

def _setup_monthly_txs(conn, ref, desc, amount, months):
    """Add monthly transactions for given YYYY-MM list."""
    for ym in months:
        y, m = int(ym[:4]), int(ym[5:7])
        _add_tx(conn, desc, ref, amount, date(y, m, 5), analysis_month=ym)


def test_group_produces_single_pattern():
    conn = _make_conn()
    _setup_monthly_txs(conn, "Telia", "Telia", -199.0, ["2025-01","2025-02","2025-03","2025-04","2025-05","2025-06"])
    _setup_monthly_txs(conn, "Bredband", "Bredband", -299.0, ["2025-01","2025-02","2025-03","2025-04","2025-05","2025-06"])
    insert_group(conn, "phone and internet", "expenses", "#3498db")
    add_group_member(conn, "phone and internet", "Telia", "Telia")
    add_group_member(conn, "phone and internet", "Bredband", "Bredband")

    patterns, one_offs = build_patterns(conn, reference_date=date(2025, 7, 1))
    assert len(patterns) == 1
    p = patterns[0]
    assert p.description == "phone and internet"
    assert p.cadence == "monthly"
    assert p.color == "#3498db"
    # Individual Telia / Bredband should not appear
    descs = {p.description for p in patterns}
    assert "Telia" not in descs
    assert "Bredband" not in descs
    assert len(one_offs) == 0


def test_group_amount_is_sum_of_members():
    conn = _make_conn()
    _setup_monthly_txs(conn, "Telia", "Telia", -199.0, ["2025-01","2025-02","2025-03","2025-04"])
    _setup_monthly_txs(conn, "Bredband", "Bredband", -299.0, ["2025-01","2025-02","2025-03","2025-04"])
    insert_group(conn, "phone", "expenses", "#aabbcc")
    add_group_member(conn, "phone", "Telia", "Telia")
    add_group_member(conn, "phone", "Bredband", "Bredband")

    patterns, _ = build_patterns(conn, reference_date=date(2025, 5, 1))
    assert len(patterns) == 1
    p = patterns[0]
    assert p.amount_type == "fixed"
    assert abs(p.fixed_amount - 498.0) < 0.01


def test_ungrouped_txs_still_appear():
    conn = _make_conn()
    _setup_monthly_txs(conn, "Telia", "Telia", -199.0, ["2025-01","2025-02","2025-03","2025-04"])
    _setup_monthly_txs(conn, "Spotify", "Spotify", -119.0, ["2025-01","2025-02","2025-03","2025-04"])
    insert_group(conn, "phone", "expenses")
    add_group_member(conn, "phone", "Telia", "Telia")

    patterns, _ = build_patterns(conn, reference_date=date(2025, 5, 1))
    descs = {p.description for p in patterns}
    assert "phone" in descs
    assert "Spotify" in descs
    assert "Telia" not in descs


def test_group_single_member_alias():
    conn = _make_conn()
    _setup_monthly_txs(conn, "OCR123", "Electricity", -450.0, ["2025-01","2025-02","2025-03"])
    insert_group(conn, "El", "expenses", "#ff0000")
    add_group_member(conn, "El", "OCR123", "Electricity")

    patterns, _ = build_patterns(conn, reference_date=date(2025, 4, 1))
    assert len(patterns) == 1
    assert patterns[0].description == "El"
    assert patterns[0].color == "#ff0000"


# ── exclude_from_prediction ────────────────────────────────────────────────────

def test_set_group_exclude_roundtrip():
    conn = _make_conn()
    insert_group(conn, "phone", "expenses")
    assert fetch_groups(conn)[0]["exclude_from_prediction"] == 0

    assert set_group_exclude(conn, "phone", True) is True
    assert fetch_groups(conn)[0]["exclude_from_prediction"] == 1

    assert set_group_exclude(conn, "phone", False) is True
    assert fetch_groups(conn)[0]["exclude_from_prediction"] == 0


def test_set_group_exclude_missing_group_returns_false():
    conn = _make_conn()
    assert set_group_exclude(conn, "nonexistent", True) is False


def test_build_patterns_propagates_exclude_flag():
    conn = _make_conn()
    _setup_monthly_txs(conn, "Telia", "Telia", -199.0, ["2025-01","2025-02","2025-03","2025-04"])
    insert_group(conn, "phone", "expenses")
    add_group_member(conn, "phone", "Telia", "Telia")
    set_group_exclude(conn, "phone", True)

    patterns, _ = build_patterns(conn, reference_date=date(2025, 5, 1))
    assert len(patterns) == 1
    assert patterns[0].exclude_from_prediction is True


def test_update_group_color_roundtrip():
    conn = _make_conn()
    insert_group(conn, "phone", "expenses", "#ff0000")
    result = update_group_color(conn, "phone", "#00ff00")
    assert result is True
    grp = conn.execute("SELECT color FROM groups WHERE name='phone'").fetchone()
    assert grp["color"] == "#00ff00"


def test_update_group_color_missing_group_returns_false():
    conn = _make_conn()
    assert update_group_color(conn, "nonexistent", "#ff0000") is False


def test_fetch_all_group_member_keys_returns_all_groups():
    conn = _make_conn()
    insert_group(conn, "G1", "expenses", "#ff0000")
    insert_group(conn, "G2", "expenses", "#00ff00")
    add_group_member(conn, "G1", "RefA", "DescA")
    add_group_member(conn, "G2", "RefB", "DescB")
    keys = fetch_all_group_member_keys(conn)
    assert keys == {("RefA", "DescA"), ("RefB", "DescB")}


def test_fetch_all_group_member_keys_empty():
    conn = _make_conn()
    assert fetch_all_group_member_keys(conn) == set()
