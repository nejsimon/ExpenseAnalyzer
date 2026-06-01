import csv
import io
from datetime import date

from expense_analyzer.output import render_import_result, render_prediction, render_recurring_summary
from expense_analyzer.predictor import PredictionLine
from expense_analyzer.recurring import OneOff, RecurringPattern


def _pattern(desc, cadence, amount_type, fixed=None, mn=None, mx=None, status="active"):
    return RecurringPattern(
        reference=desc,
        description=desc,
        cadence=cadence,
        amount_type=amount_type,
        fixed_amount=fixed,
        min_amount=mn,
        max_amount=mx,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 6, 1) if status == "canceled" else None,
        status=status,
        amounts=[-(fixed or mn or 0)],
    )


def _one_off(desc, d, amount):
    return OneOff(reference=desc, description=desc, booking_date=d, amount=amount)


def _line(desc, cadence, predicted, amount_type="fixed", range_str=""):
    return PredictionLine(
        description=desc,
        cadence=cadence,
        predicted_amount=predicted,
        amount_type=amount_type,
        range_str=range_str,
    )


# --- render_import_result ---

def test_import_result_table(capsys):
    render_import_result(12, 3, "table")
    assert "Inserted 12, skipped 3" in capsys.readouterr().out


def test_import_result_csv(capsys):
    render_import_result(5, 2, "csv")
    out = capsys.readouterr().out
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == ["inserted", "skipped"]
    assert rows[1] == ["5", "2"]


# --- render_recurring_summary ---

def test_recurring_summary_table_headers(capsys):
    p = _pattern("Spotify", "monthly", "fixed", fixed=119.0)
    render_recurring_summary([p], [], [], [], "table")
    out = capsys.readouterr().out
    assert "Merchant" in out
    assert "Cadence" in out
    assert "Amount" in out
    assert "Status" in out


def test_recurring_summary_fixed_amount_format(capsys):
    p = _pattern("Spotify", "monthly", "fixed", fixed=119.0)
    render_recurring_summary([p], [], [], [], "table")
    out = capsys.readouterr().out
    assert "119.00 (fixed)" in out
    assert "active" in out


def test_recurring_summary_variable_amount_format(capsys):
    p = _pattern("El", "monthly", "variable", mn=400.0, mx=820.0)
    render_recurring_summary([p], [], [], [], "table")
    out = capsys.readouterr().out
    assert "400.00" in out
    assert "820.00" in out
    assert "(var)" in out


def test_recurring_summary_canceled_status(capsys):
    p = _pattern("Gym", "monthly", "fixed", fixed=300.0, status="canceled")
    render_recurring_summary([p], [], [], [], "table")
    out = capsys.readouterr().out
    assert "canceled" in out
    assert "2025-06" in out


def test_recurring_summary_one_offs(capsys):
    render_recurring_summary([], [_one_off("IKEA", date(2026, 3, 5), -1500.0)], [], [], "table")
    out = capsys.readouterr().out
    assert "IKEA" in out
    assert "1500.00" in out


def test_recurring_summary_empty(capsys):
    render_recurring_summary([], [], [], [], "table")
    out = capsys.readouterr().out
    assert "(none)" in out


def test_recurring_summary_csv_structure(capsys):
    p = _pattern("Spotify", "monthly", "fixed", fixed=119.0)
    o = _one_off("IKEA", date(2026, 3, 5), -1500.0)
    render_recurring_summary([p], [o], [], [], "csv")
    out = capsys.readouterr().out
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[1] == ["Merchant", "Cadence", "Amount", "Start", "Status"]
    assert rows[2][0] == "Spotify"


def test_recurring_summary_shows_income_section(capsys):
    inc = _pattern("Lön", "monthly", "fixed", fixed=25000.0)
    render_recurring_summary([], [], [inc], [], "table")
    out = capsys.readouterr().out
    assert "Income" in out
    assert "Lön" in out
    assert "25000.00" in out


def test_recurring_summary_deposits_only_hides_expenses(capsys):
    exp = _pattern("Spotify", "monthly", "fixed", fixed=119.0)
    inc = _pattern("Lön", "monthly", "fixed", fixed=25000.0)
    render_recurring_summary([exp], [], [inc], [], "table", deposits_only=True)
    out = capsys.readouterr().out
    assert "Spotify" not in out
    assert "Lön" in out


# --- render_prediction ---

def test_prediction_table_contains_merchant(capsys):
    render_prediction([_line("Spotify", "monthly", 119.0)], [], "2026-05", "table")
    out = capsys.readouterr().out
    assert "Spotify" in out
    assert "119.00" in out


def test_prediction_table_expense_total(capsys):
    lines = [_line("Spotify", "monthly", 119.0), _line("Lf Uppsala", "monthly", 195.0)]
    render_prediction(lines, [], "2026-05", "table")
    out = capsys.readouterr().out
    assert "314.00" in out


def test_prediction_table_two_decimal_places(capsys):
    render_prediction([_line("X", "monthly", 195.0)], [], "2026-05", "table")
    out = capsys.readouterr().out
    assert "195.00" in out


def test_prediction_table_variable_shows_range(capsys):
    render_prediction(
        [_line("El", "monthly", 490.0, amount_type="variable", range_str="380.00–610.00")],
        [],
        "2026-05",
        "table",
    )
    out = capsys.readouterr().out
    assert "380.00–610.00" in out


def test_prediction_empty(capsys):
    render_prediction([], [], "2026-05", "table")
    out = capsys.readouterr().out
    assert "No recurring" in out


def test_prediction_shows_income_and_net(capsys):
    render_prediction(
        [_line("Spotify", "monthly", 119.0)],
        [_line("Lön", "monthly", 25000.0)],
        "2026-05",
        "table",
    )
    out = capsys.readouterr().out
    assert "Lön" in out
    assert "25000.00" in out
    assert "Net" in out
    # Net = income - expenses = 25000 - 119 = 24881.00
    assert "24881.00" in out


def test_prediction_csv_structure(capsys):
    lines = [_line("Spotify", "monthly", 119.0), _line("Netflix", "monthly", 99.0)]
    render_prediction(lines, [], "2026-05", "csv")
    out = capsys.readouterr().out
    rows = [r for r in csv.reader(io.StringIO(out)) if r]  # skip blank rows
    assert any(r == ["Merchant", "Cadence", "Predicted (SEK)", "Range"] for r in rows)
    assert any(r[0] == "Expenses" for r in rows)
    assert any(r[0] == "Net" for r in rows)
