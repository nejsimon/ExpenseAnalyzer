import sqlite3
from datetime import date, timedelta

import pytest

from expense_analyzer.db import add_group_member, init_db, insert_group, insert_transaction
from expense_analyzer.predictor import PredictionLine, _hits_month, _weighted_average, enrich_with_actuals, predict_month
from expense_analyzer.recurring import RecurringPattern, build_patterns


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _add_tx(conn, desc, ref, amount, booking_date):
    import hashlib
    d = booking_date.isoformat()
    h = hashlib.sha256(f"{d}|{ref}|{desc}|{amount}".encode()).hexdigest()
    insert_transaction(conn, {
        "row_number": 1, "clearing": "", "account": "", "product": "",
        "currency": "SEK", "booking_date": d, "transaction_date": d,
        "value_date": d, "reference": ref, "description": desc,
        "amount": amount, "balance": 0.0, "import_hash": h,
        "analysis_month": d[:7],
    })


def _make_pattern(cadence, amount_type, amounts, start, status="active"):
    abs_a = [abs(a) for a in amounts]
    return RecurringPattern(
        reference="ref",
        description="desc",
        cadence=cadence,
        amount_type=amount_type,
        fixed_amount=abs_a[-1] if amount_type == "fixed" else None,
        min_amount=min(abs_a) if amount_type == "variable" else None,
        max_amount=max(abs_a) if amount_type == "variable" else None,
        start_date=start,
        end_date=None if status == "active" else start,
        status=status,
        amounts=amounts,
    )


# --- _weighted_average ---

def test_weighted_average_equal_weights_single():
    assert _weighted_average([-100.0]) == pytest.approx(100.0)


def test_weighted_average_gives_more_weight_to_recent():
    # [100, 200]: weight 1→100, weight 2→200 → (1*100 + 2*200) / 3 = 500/3 ≈ 166.67
    assert _weighted_average([-100.0, -200.0]) == pytest.approx(500 / 3)


def test_weighted_average_all_same():
    assert _weighted_average([-50.0, -50.0, -50.0]) == pytest.approx(50.0)


# --- _hits_month ---

def test_hits_monthly_always():
    p = _make_pattern("monthly", "fixed", [-100], date(2025, 1, 1))
    assert _hits_month(p, 2026, 4)
    assert _hits_month(p, 2025, 6)


def test_hits_quarterly_every_third():
    p = _make_pattern("quarterly", "fixed", [-100], date(2025, 1, 15))
    # start = Jan 2025 (index 2025*12+1=24301)
    # Jan, Apr, Jul, Oct should hit
    assert _hits_month(p, 2025, 4)
    assert _hits_month(p, 2025, 7)
    assert not _hits_month(p, 2025, 2)
    assert not _hits_month(p, 2025, 3)


def test_hits_yearly_same_month_only():
    p = _make_pattern("yearly", "fixed", [-100], date(2024, 3, 10))
    assert _hits_month(p, 2026, 3)
    assert not _hits_month(p, 2026, 4)
    assert not _hits_month(p, 2026, 2)


def test_hits_quarterly_uses_last_analysis_month_as_anchor():
    # start_date = 2024-04, last_analysis_month = 2026-03
    # Without anchor fix: target 2026-04 hits (diff from start = 24 months = 8 quarters)
    # With anchor fix: anchor is 2026-03, diff to 2026-04 = 1 month → miss; 2026-06 = 3 months → hit
    p = _make_pattern("quarterly", "fixed", [-300], date(2024, 4, 15))
    p.last_analysis_month = "2026-03"
    assert not _hits_month(p, 2026, 4)
    assert _hits_month(p, 2026, 6)


def test_hits_yearly_uses_last_analysis_month_as_anchor():
    # start_date = 2024-04, last_analysis_month = 2025-03 → yearly hits in March
    p = _make_pattern("yearly", "fixed", [-100], date(2024, 4, 1))
    p.last_analysis_month = "2025-03"
    assert _hits_month(p, 2026, 3)
    assert not _hits_month(p, 2026, 4)


def test_hits_before_start_returns_false():
    p = _make_pattern("monthly", "fixed", [-100], date(2026, 6, 1))
    assert not _hits_month(p, 2026, 5)
    assert not _hits_month(p, 2025, 12)


# --- predict_month ---

def test_predict_fixed_uses_fixed_amount():
    p = _make_pattern("monthly", "fixed", [-195.0], date(2025, 1, 1))
    lines = predict_month([p], "2026-05")
    assert len(lines) == 1
    assert lines[0].predicted_amount == pytest.approx(195.0)


def test_predict_variable_uses_weighted_average():
    amounts = [-100.0, -200.0, -300.0]
    p = _make_pattern("monthly", "variable", amounts, date(2025, 1, 1))
    lines = predict_month([p], "2026-05")
    # weights: 1,2,3 → (1*100 + 2*200 + 3*300) / 6 = 1400/6 ≈ 233.33
    assert lines[0].predicted_amount == pytest.approx(1400 / 6)


def test_predict_excludes_canceled():
    p = _make_pattern("monthly", "fixed", [-100.0], date(2025, 1, 1), status="canceled")
    lines = predict_month([p], "2026-05")
    assert lines == []


def test_predict_quarterly_skips_off_months():
    p = _make_pattern("quarterly", "fixed", [-500.0], date(2025, 1, 15))
    # April 2025: index=24304, start=24301, diff=3 → hits
    assert len(predict_month([p], "2025-04")) == 1
    # February: diff=1 → miss
    assert len(predict_month([p], "2025-02")) == 0


def test_predict_total_sums_all_lines():
    conn = _make_conn()
    # 4 occurrences; last one on 2025-06-12 — well within the 45-day active window
    base = date(2025, 3, 15)
    for i in range(4):
        _add_tx(conn, "Spotify", "Spotify", -119.0, base + timedelta(days=30 * i))
        _add_tx(conn, "Netflix", "Netflix", -99.0, base + timedelta(days=30 * i))
    patterns, _ = build_patterns(conn, reference_date=date(2025, 6, 20))
    lines = predict_month(patterns, "2025-07")
    total = sum(l.predicted_amount for l in lines)
    assert total == pytest.approx(218.0)


def test_predict_range_str_set_for_variable():
    amounts = [-400.0, -600.0, -820.0]
    p = _make_pattern("monthly", "variable", amounts, date(2025, 1, 1))
    lines = predict_month([p], "2026-05")
    assert "400" in lines[0].range_str
    assert "820" in lines[0].range_str


# --- enrich_with_actuals ---

def _make_line(description: str, reference: str = "", color: str | None = None) -> PredictionLine:
    return PredictionLine(
        description=description,
        cadence="monthly",
        predicted_amount=100.0,
        amount_type="fixed",
        range_str="",
        reference=reference,
        color=color,
    )


def test_enrich_individual_pattern_sets_actual_amount():
    conn = _make_conn()
    _add_tx(conn, "Spotify", "Spotify", -119.0, date(2026, 4, 5))
    line = _make_line("Spotify", reference="Spotify")
    enrich_with_actuals(conn, [line], "2026-04", "expenses")
    assert line.actual_amount == pytest.approx(119.0)
    assert line.member_count is None
    assert line.members_seen is None


def test_enrich_individual_pattern_no_match_leaves_none():
    conn = _make_conn()
    line = _make_line("Spotify", reference="Spotify")
    enrich_with_actuals(conn, [line], "2026-04", "expenses")
    assert line.actual_amount is None


def test_enrich_group_pattern_full_payment():
    conn = _make_conn()
    insert_group(conn, "Phone bundle", "expenses", "#ff0000")
    add_group_member(conn, "Phone bundle", "TeliaRef", "Telia")
    add_group_member(conn, "Phone bundle", "ComviqRef", "Comviq")
    _add_tx(conn, "Telia", "TeliaRef", -199.0, date(2026, 4, 10))
    _add_tx(conn, "Comviq", "ComviqRef", -99.0, date(2026, 4, 12))
    line = _make_line("Phone bundle", color="#ff0000")
    enrich_with_actuals(conn, [line], "2026-04", "expenses")
    assert line.actual_amount == pytest.approx(298.0)
    assert line.member_count == 2
    assert line.members_seen == 2


def test_predict_excludes_excluded_from_prediction_pattern():
    p = _make_pattern("monthly", "fixed", [-100.0], date(2025, 1, 1))
    p.exclude_from_prediction = True
    lines = predict_month([p], "2026-05")
    assert lines == []


def test_enrich_group_pattern_partial_payment():
    conn = _make_conn()
    insert_group(conn, "Phone bundle", "expenses", "#ff0000")
    add_group_member(conn, "Phone bundle", "TeliaRef", "Telia")
    add_group_member(conn, "Phone bundle", "ComviqRef", "Comviq")
    _add_tx(conn, "Telia", "TeliaRef", -199.0, date(2026, 4, 10))
    line = _make_line("Phone bundle", color="#ff0000")
    enrich_with_actuals(conn, [line], "2026-04", "expenses")
    assert line.actual_amount == pytest.approx(199.0)
    assert line.member_count == 2
    assert line.members_seen == 1
