# 11 — Deposits

**Status:** [x] done

## Description

Extend all analysis features to cover incoming transactions (deposits/income) alongside outgoing expenses. Deposits are rows with a positive `amount`.

## Acceptance Criteria

- `analyze` shows a deposits section (recurring income + one-off deposits) below the expenses section.
- `predict` shows expected income alongside expected expenses, and a net line.
- `stats` shows income rows (already specified in spec 09).
- Hole detection (spec 08) also checks for missing months in income.
- Recurring deposit detection uses the same cadence algorithm as expenses.
- `--deposits-only` flag shows only the deposits section.

## Output Example (`analyze`)

```
=== Expenses ===
Merchant         Cadence   Amount        Start    Status
...

=== Income ===
Merchant         Cadence   Amount        Start    Status
──────────────────────────────────────────────────────
Löneutbetalning  monthly   25 000 (fixed) 2024-01  active
```

```
=== Prediction for 2026-05 ===
              Predicted
Expenses       4 120.00
Income        25 000.00
──────────────────────
Net           20 880.00
```

## Implementation Notes

- `fetch_transactions` already has `outgoing_only: bool` — add `incoming_only: bool` parameter (mutually exclusive; default both `False` = return all).
- `build_patterns(conn, direction='expenses'|'income'|'all')` — add `direction` parameter.
- In `recurring.py`, deposits use `amount > 0` filter instead of `amount < 0`.
- In `predictor.py`, `predict_month` returns two lists: `expense_lines` and `income_lines`.
- In `output.py`, `render_recurring_summary` renders two sections.
- Hole detection check 2 in `importer.py`: run separately for outgoing and incoming batches.
- Amount display for deposits: show as positive values (strip the sign).
