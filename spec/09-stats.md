# 09 — Stats

**Status:** [x] done

## Description

A `stats` command that shows total and average expenses (and income) on a per-calendar-year basis. For the current year, incomplete months are filled with predicted values.

## Acceptance Criteria

- `utgiftsanalys stats` prints a table with one row per year.
- Each row shows: year, actual total expenses, number of actual months, avg per month (actual), predicted total for remaining months, and estimated full-year total.
- Current year shows actuals for completed months + predictions for months not yet in the DB.
- Past years show actuals only (no prediction column, or "—").
- Income row (or column) is shown alongside expenses when deposit data exists.
- `--output csv` works.
- `--account ACCOUNT` filters to one account.

## Output Example

```
Year    Expenses (actual)  Months  Avg/month  Predicted remaining  Est. full year
──────────────────────────────────────────────────────────────────────────────────
2024      48 320.00          12    4 026.67           —              48 320.00
2025      51 840.00          12    4 320.00           —              51 840.00
2026      14 200.00           4    3 550.00       21 300.00          35 500.00

Income
2024      312 000.00         12   26 000.00           —             312 000.00
2026       84 500.00          4   21 125.00      126 750.00         211 250.00
```

## Implementation Notes

- New `stats.py` module with `compute_stats(conn, account=None) -> list[YearStats]`.
- `YearStats` dataclass: `year, actual_expense, actual_income, actual_months, avg_expense, avg_income, predicted_expense_remaining, predicted_income_remaining`.
- "Completed months" = distinct `analysis_month` values present in the DB for that year.
- Predicted remaining = months in the calendar year that have NO transactions in the DB yet. For each such month, call `predict_month` (expenses) and the income equivalent.
- Current year detection: `date.today().year`.
- Past years: `predicted_expense_remaining = None`; display as "—".
- `avg_expense = actual_expense / actual_months` (avoid division by zero).
- New CLI command: `utgiftsanalys stats [--output table|csv] [--account ACCOUNT]`.
