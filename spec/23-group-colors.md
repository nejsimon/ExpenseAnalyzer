# 23 — Group Colors in Tables and Charts

**Status:** [x] done

## Description

Groups already store a hex color but it is never rendered. This spec wires colors into two places: (1) the monthly expenses bar chart becomes a stacked bar where each segment is a group (or "Other" for uncategorized expenses), and (2) tables in the Predict and Analyze tabs gain a color swatch column for rows that belong to a group.

## Acceptance Criteria

- The Charts tab "Monthly expenses" chart is replaced with a stacked bar chart whose segments are the expense groups plus an "Other" segment for uncategorized transactions. Each segment uses the group's stored hex color; "Other" uses `#888888`.
- The same stacked layout is applied to the "Monthly income" chart using income groups.
- The Predict tab expense and income tables gain a "Color" column rendered as a color swatch. Individual patterns (no group) show an empty/white swatch.
- The Analyze tab recurring-patterns flat table gains the same "Color" column.
- Future months (non-current-month in Predict) also show the color column.
- No change to the Charts tab's prediction-deviation charts (charts 3 and 4).
- `uv run mypy utgiftsanalys/` exits 0. `uv run ruff check utgiftsanalys/` exits 0. All existing tests pass.

## New TypedDict and Function (chart_data.py)

```python
class GroupAmount(TypedDict):
    month: str
    group: str
    color: str
    amount: float
```

```python
def monthly_group_breakdown(
    conn: sqlite3.Connection,
    direction: str = "expenses",
    account: str | None = None,
) -> list[GroupAmount]:
```

**Logic:**

1. Fetch all groups for `direction` with their colors.
2. Build a lookup `member_key_to_group: dict[tuple[str, str], tuple[str, str]]` mapping `(reference, description)` → `(group_name, color)`.
3. Fetch all months via `fetch_months(conn, account=account)`.
4. For each month, fetch transactions with `outgoing_only=(direction == "expenses")` / `incoming_only=(direction == "income")`.
5. For each transaction, look up its group. Accumulate `abs(tx["amount"])` into a `totals: dict[tuple[str, str], float]` keyed by `(group_name, color)`, using `("Other", "#888888")` if not in any group.
6. Emit one `GroupAmount` record per `(month, group, color)` pair with a non-zero amount.

The function should be cached in the UI alongside `_cached_actuals` (same `ttl=60` pattern).

## Charts Tab Changes (ui.py)

### Replace the simple bar charts

Replace the "Monthly expenses" and "Monthly income" `mark_bar()` charts with stacked bars using `monthly_group_breakdown()`.

**Expenses stacked bar:**

```python
breakdown_exp = _cached_group_breakdown(db_path, "expenses", account)
breakdown_exp = [r for r in breakdown_exp if month_from <= r["month"] <= month_to]
if breakdown_exp:
    df_exp = pd.DataFrame(breakdown_exp)
    groups_exp = df_exp[["group", "color"]].drop_duplicates()
    domain_exp = groups_exp["group"].tolist()
    range_exp  = groups_exp["color"].tolist()
    chart1 = (
        alt.Chart(df_exp)
        .mark_bar()
        .encode(
            x=alt.X("month:N", title="Month", sort=None),
            y=alt.Y("amount:Q", title="SEK"),
            color=alt.Color(
                "group:N",
                scale=alt.Scale(domain=domain_exp, range=range_exp),
                title="Group",
            ),
            order=alt.Order("group:N"),
            tooltip=["month", "group", alt.Tooltip("amount:Q", format=".2f")],
        )
    )
    st.altair_chart(chart1, width="stretch")
```

Apply the same pattern for the income chart using `direction="income"`.

**Fallback:** If `breakdown_exp` is empty (no data in range), show the existing simple bar chart using `df_actuals` as before.

### Cache helper

```python
@st.cache_data(ttl=60)
def _cached_group_breakdown(
    db_path: str, direction: str, account: str | None
) -> list[GroupAmount]:
    conn = get_connection(db_path)
    return monthly_group_breakdown(conn, direction=direction, account=account)
```

Import `GroupAmount` and `monthly_group_breakdown` from `utgiftsanalys.chart_data`.

## Predict Tab: Color Column (ui.py)

In `_prediction_df()`, always include a "Color" column (not only when `show_actuals` is True):

```python
row["Color"] = line.color if line.color is not None else "#ffffff"
```

In `_tab_predict()`, when rendering with `st.dataframe`, pass `column_config`:

```python
st.dataframe(
    df,
    width="stretch",
    hide_index=True,
    column_config={"Color": st.column_config.ColorColumn("Color", width="small")},
)
```

## Analyze Tab: Color Column (ui.py)

In `_pattern_df()`, add a "Color" key to each row dict:

```python
"Color": p.color if p.color is not None else "#ffffff",
```

In `_render_recurring_section()`, pass `column_config` when rendering the individual table:

```python
st.dataframe(
    df,
    width="stretch",
    hide_index=True,
    column_config={"Color": st.column_config.ColorColumn("Color", width="small")},
)
```

## Implementation Notes

- `monthly_group_breakdown()` works at the raw-transaction level, not via `build_patterns()`. This is intentional: it must correctly attribute transactions to groups even for months where the group pattern was not yet detected as recurring.
- The "Other" color `#888888` is a constant in `chart_data.py`: `_OTHER_COLOR = "#888888"`.
- The stacked bar's `order` encoding sorts segments consistently across months so the same group always occupies the same vertical position. Sorting by `group:N` (alphabetical) is sufficient.
- No changes to `output.py` — the CLI table does not gain a color column (terminal hex strings are not useful).
- No changes to `predictor.py` or `recurring.py`.
- New tests in `tests/test_chart_data.py`: `monthly_group_breakdown()` returns correct per-group amounts; uncategorized transactions appear under "Other"; a month with no transactions for a group produces no record for that group.
