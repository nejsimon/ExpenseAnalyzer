# 15 — Charts

**Status:** [x] done

## Description

Add a Charts tab to the Streamlit UI (spec 14) with visual summaries of historical expense/income data and prediction quality. A date range picker scopes all charts to a selected interval.

## Acceptance Criteria

- A "Charts" tab appears in the Streamlit UI alongside the existing five tabs.
- Four charts are shown: monthly expenses, monthly income, predicted vs actual expenses, prediction deviation.
- A date range picker (month granularity) filters all charts.
- Charts update when the sidebar account selector changes.
- Months with no data are omitted — no zero-filled gaps.

## Charts

### Date range filter
`st.date_input("Date range", value=(first_month_in_db, last_month_in_db))` — all four charts respect this range.

### Chart 1 — Monthly expenses
Bar chart. X-axis: month (YYYY-MM). Y-axis: total actual outgoing amount (SEK). One bar per month.

### Chart 2 — Monthly income
Bar chart. X-axis: month. Y-axis: total actual incoming amount (SEK).

### Chart 3 — Predicted vs actual expenses
Line chart with two series on the same axes:
- **Actual**: sum of outgoing transactions per month.
- **Predicted**: `predict_month(exp_patterns, month)` total, using all-time patterns (noted in UI as approximate).
Past months only (months where actual data exists).

### Chart 4 — Prediction deviation
Bar chart: `predicted_expenses − actual_expenses` per month.
- Positive value = over-predicted (red bar).
- Negative value = under-predicted (green bar).

## Implementation Notes

- New file `utgiftsanalys/chart_data.py` with two functions:
  ```python
  def monthly_actuals(conn, account=None) -> list[dict]:
      # [{month, expenses, income}, ...]
      # For each month in fetch_months(conn): sum amounts by sign

  def monthly_with_predictions(conn, account=None) -> list[dict]:
      # [{month, actual_expenses, predicted_expenses}, ...]
      # Build all-time exp_patterns once, then predict_month for each past month
  ```
- Add `altair>=5.0` to the `ui` optional dep group in `pyproject.toml`.
- Use `st.altair_chart` for all four charts (gives colour control and tooltips).
- For chart 4, encode bar colour conditionally: red if deviation > 0, green if ≤ 0, using Altair's `condition` encoding.
- Cache `monthly_actuals` result with `st.cache_data(ttl=60)` to avoid recomputation on every widget interaction.
