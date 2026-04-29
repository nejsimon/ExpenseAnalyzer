import csv
import sqlite3
import sys

from tabulate import tabulate

from .adapters import CsvAdapter
from .predictor import PredictionLine
from .recurring import OneOff, RecurringPattern
from .stats import YearStats


def _fmt_amount(pattern: RecurringPattern) -> str:
    if pattern.amount_type == "fixed":
        return f"{pattern.fixed_amount:.2f} (fixed)"
    return f"{pattern.min_amount:.2f}–{pattern.max_amount:.2f} (var)"


def _fmt_status(pattern: RecurringPattern) -> str:
    if pattern.status == "canceled":
        return f"canceled (last: {pattern.end_date})"
    return "active"


def _render_pattern_section(
    patterns: list[RecurringPattern],
    one_offs: list[OneOff],
    title: str,
    fmt: str,
) -> None:
    rec_rows = [
        [p.description, p.cadence, _fmt_amount(p), str(p.start_date)[:7], _fmt_status(p)]
        for p in patterns
    ]
    rec_headers = ["Merchant", "Cadence", "Amount", "Start", "Status"]
    off_rows = [[o.description, str(o.booking_date), f"{abs(o.amount):.2f}"] for o in one_offs]
    off_headers = ["Merchant", "Date", "Amount"]

    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow([f"# {title}"])
        w.writerow(rec_headers)
        w.writerows(rec_rows)
        w.writerow(["# One-offs"])
        w.writerow(off_headers)
        w.writerows(off_rows)
        w.writerow([])
    else:
        print(f"=== {title} ===")
        if rec_rows:
            print(
                tabulate(rec_rows, headers=rec_headers, tablefmt="rounded_outline", floatfmt=".2f")
            )
        else:
            print("  (none)")
        print(f"\nOne-offs ({title})")
        if off_rows:
            print(
                tabulate(off_rows, headers=off_headers, tablefmt="rounded_outline", floatfmt=".2f")
            )
        else:
            print("  (none)")
        print()


def render_recurring_summary(
    exp_patterns: list[RecurringPattern],
    exp_one_offs: list[OneOff],
    inc_patterns: list[RecurringPattern],
    inc_one_offs: list[OneOff],
    fmt: str = "table",
    deposits_only: bool = False,
) -> None:
    if not deposits_only:
        _render_pattern_section(exp_patterns, exp_one_offs, "Expenses", fmt)
    _render_pattern_section(inc_patterns, inc_one_offs, "Income", fmt)


def render_prediction(
    exp_lines: list[PredictionLine],
    inc_lines: list[PredictionLine],
    target_month: str,
    fmt: str = "table",
) -> None:
    detail_headers = ["Merchant", "Cadence", "Predicted (SEK)", "Range"]
    exp_rows = [
        [ln.description, ln.cadence, f"{ln.predicted_amount:.2f}", ln.range_str] for ln in exp_lines
    ]
    inc_rows = [
        [ln.description, ln.cadence, f"{ln.predicted_amount:.2f}", ln.range_str] for ln in inc_lines
    ]
    exp_total = sum(ln.predicted_amount for ln in exp_lines)
    inc_total = sum(ln.predicted_amount for ln in inc_lines)
    net = inc_total - exp_total

    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(["# Expenses"])
        w.writerow(detail_headers)
        w.writerows(exp_rows)
        w.writerow(["TOTAL", "", f"{exp_total:.2f}", ""])
        w.writerow([])
        w.writerow(["# Income"])
        w.writerow(detail_headers)
        w.writerows(inc_rows)
        w.writerow(["TOTAL", "", f"{inc_total:.2f}", ""])
        w.writerow([])
        w.writerow(["# Summary"])
        w.writerow(["Expenses", f"{exp_total:.2f}"])
        w.writerow(["Income", f"{inc_total:.2f}"])
        w.writerow(["Net", f"{net:.2f}"])
    else:
        print(f"Prediction for {target_month}")
        if not exp_rows and not inc_rows:
            print("  No recurring transactions expected.")
            return
        print("\nExpenses")
        if exp_rows:
            print(
                tabulate(
                    exp_rows, headers=detail_headers, tablefmt="rounded_outline", floatfmt=".2f"
                )
            )
        else:
            print("  (none)")
        print("\nIncome")
        if inc_rows:
            print(
                tabulate(
                    inc_rows, headers=detail_headers, tablefmt="rounded_outline", floatfmt=".2f"
                )
            )
        else:
            print("  (none)")
        summary_rows = [
            ["Expenses", f"{exp_total:.2f}"],
            ["Income", f"{inc_total:.2f}"],
            ["Net", f"{net:.2f}"],
        ]
        print()
        print(
            tabulate(
                summary_rows,
                headers=["", "Predicted (SEK)"],
                tablefmt="rounded_outline",
                floatfmt=".2f",
            )
        )


def render_stats(stats: list[YearStats], fmt: str = "table") -> None:
    def _fmt_pred(v: float | None) -> str:
        return f"{v:.2f}" if v is not None else "—"

    def _est_full(s: YearStats, direction: str) -> str:
        actual = s.actual_expense if direction == "expense" else s.actual_income
        pred = (
            s.predicted_expense_remaining
            if direction == "expense"
            else s.predicted_income_remaining
        )
        if pred is None:
            return f"{actual:.2f}"
        return f"{actual + pred:.2f}"

    headers = ["Year", "Actual", "Months", "Avg/month", "Predicted remaining", "Est. full year"]

    def _rows(direction: str) -> list[list[str]]:
        rows = []
        for s in stats:
            actual = s.actual_expense if direction == "expense" else s.actual_income
            avg = s.avg_expense if direction == "expense" else s.avg_income
            pred = (
                s.predicted_expense_remaining
                if direction == "expense"
                else s.predicted_income_remaining
            )
            if actual == 0 and pred is None:
                continue
            rows.append(
                [
                    str(s.year),
                    f"{actual:.2f}",
                    str(s.actual_months),
                    f"{avg:.2f}",
                    _fmt_pred(pred),
                    _est_full(s, direction),
                ]
            )
        return rows

    expense_rows = _rows("expense")
    income_rows = _rows("income")

    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(["# Expenses"])
        w.writerow(headers)
        w.writerows(expense_rows)
        if income_rows:
            w.writerow([])
            w.writerow(["# Income"])
            w.writerow(headers)
            w.writerows(income_rows)
    else:
        print("Expenses")
        if expense_rows:
            print(
                tabulate(expense_rows, headers=headers, tablefmt="rounded_outline", floatfmt=".2f")
            )
        else:
            print("  (no data)")
        if income_rows:
            print("\nIncome")
            print(
                tabulate(income_rows, headers=headers, tablefmt="rounded_outline", floatfmt=".2f")
            )


def render_accounts(accounts: list[tuple[str, int]], fmt: str = "table") -> None:
    headers = ["Account", "Transactions"]
    rows = [[a, str(n)] for a, n in accounts]
    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(headers)
        w.writerows(rows)
    else:
        if rows:
            print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))
        else:
            print("No accounts found.")


def render_import_result(inserted: int, skipped: int, fmt: str = "table") -> None:
    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(["inserted", "skipped"])
        w.writerow([inserted, skipped])
    else:
        print(f"Inserted {inserted}, skipped {skipped}.")


def render_groups(groups: list[sqlite3.Row], fmt: str = "table") -> None:
    """Render a list of group rows (sqlite3.Row from fetch_groups)."""
    headers = ["Name", "Direction", "Color"]
    rows = [[g["name"], g["direction"], g["color"]] for g in groups]
    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(headers)
        w.writerows(rows)
    else:
        if rows:
            print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))
        else:
            print("No groups found.")


def render_adapters(adapters: list[CsvAdapter], fmt: str = "table") -> None:
    headers = ["Name", "Required columns", "Delimiter", "Decimal"]
    rows = [
        [a.name, ", ".join(a.required_columns), repr(a.delimiter), repr(a.decimal_sep)]
        for a in adapters
    ]
    if fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(headers)
        w.writerows(rows)
    else:
        if rows:
            print(tabulate(rows, headers=headers, tablefmt="rounded_outline"))
        else:
            print("No adapters registered.")
