# 20 — Current Month in Predictions

**Status:** [x] done

## Description

The predict tab and CLI currently only offer M+1 and later as target months. The current month is the most actionable prediction: it shows what is expected to be paid and how much has already been booked. This spec adds the current month as the first (default) option, fetches actual transactions already recorded in that month, and flags group patterns where only some member merchants have been seen — indicating the actual total may be incomplete.

## Acceptance Criteria

- The current month (YYYY-MM) is the first and default option in the predict month selector in both the Streamlit UI and the CLI.
- When the current month is selected, an "Actual (so far)" column appears in the expense and income prediction tables.
- The "Actual (so far)" cell shows:
  - `—` if no transactions for that pattern have been booked yet this month.
  - `{amount:.2f}` for individual patterns and fully-paid group patterns.
  - `{amount:.2f} ({X}/{Y} members)` for group patterns where fewer than all group members have been seen this month (X < Y).
- Future months still work exactly as before (no "Actual" column shown).
- `uv run mypy utgiftsanalys/` exits 0 with no new errors.
- `uv run ruff check utgiftsanalys/` exits 0 with no new violations.
- All existing tests pass (`uv run pytest`).

## PredictionLine Dataclass Extension (predictor.py)

Add five new fields with defaults so all existing callers are unaffected:

```python
@dataclass
class PredictionLine:
    description: str
    cadence: str
    predicted_amount: float
    amount_type: str
    range_str: str
    reference: str = ""                 # pattern.reference — used to match actuals
    color: str | None = None            # pattern.color — non-None marks a group pattern
    actual_amount: float | None = None  # sum of booked amounts this month
    member_count: int | None = None     # total group members (groups only)
    members_seen: int | None = None     # members with ≥1 tx this month (groups only)
```

## predict_month() Change (predictor.py)

Populate the two identity fields from the pattern when creating each `PredictionLine`. No logic change:

```python
PredictionLine(
    ...,
    reference=p.reference,
    color=p.color,
)
```

## New enrich_with_actuals() Function (predictor.py)

```python
def enrich_with_actuals(
    conn: sqlite3.Connection,
    lines: list[PredictionLine],
    month: str,
    direction: str = "expenses",
    account: str | None = None,
) -> None:
```

Mutates `lines` in-place. Steps:

1. Fetch all transactions for `month` in the given direction via `fetch_transactions(conn, month=month, outgoing_only=..., incoming_only=..., account=account)`.
2. Build `tx_index: dict[tuple[str, str], list[sqlite3.Row]]` keyed by `(reference or "", description or "")`.
3. For each line:
   - **Individual** (`line.color is None`): sum `abs(tx["amount"])` for all `tx_index[(line.reference, line.description)]` entries; store in `line.actual_amount` (leave `None` if no matches).
   - **Group** (`line.color is not None`): fetch group members using
     ```python
     grp_row = conn.execute(
         "SELECT id FROM groups WHERE name = ?", (line.description,)
     ).fetchone()
     members = fetch_group_members(conn, grp_row["id"])
     ```
     Iterate member keys, collect matching transactions, set `line.actual_amount`, `line.member_count = len(members)`, and `line.members_seen = count of member keys with ≥1 transaction`.

Imports to add in predictor.py: `sqlite3`; `fetch_transactions` and `fetch_group_members` from `.db`.

## UI Changes (ui.py)

### _tab_predict()

Replace the existing month-list construction:

```python
current_month = f"{today.year}-{today.month:02d}"
future_months: list[str] = [current_month]
m = next_month(today)
for _ in range(12):
    future_months.append(m)
    y, mo = int(m[:4]), int(m[5:7])
    mo += 1
    if mo > 12:
        y += 1
        mo = 1
    m = f"{y}-{mo:02d}"
month = st.selectbox("Month", future_months)   # default index 0 = current month
```

After calling `predict_month()`, enrich if viewing the current month:

```python
show_actuals = month == current_month
if show_actuals:
    enrich_with_actuals(conn, exp_lines, month, "expenses", account)
    enrich_with_actuals(conn, inc_lines, month, "income", account)
```

Pass `show_actuals` through to `_prediction_df()`.

### _prediction_df()

Add `show_actuals: bool = False` parameter. When `True`, append an "Actual (so far)" column:

- `line.actual_amount is None` → `"—"`
- Individual or fully-paid group (`line.color is None` or `line.members_seen == line.member_count`) → `f"{line.actual_amount:.2f}"`
- Partial group (`line.members_seen is not None and line.members_seen < line.member_count`) → `f"{line.actual_amount:.2f} ({line.members_seen}/{line.member_count} members)"`

## CLI Changes (cli.py)

Change the `predict` command default from next month to current month:

```python
if month is None:
    today = date.today()
    month = f"{today.year}-{today.month:02d}"
```

After building predictions, enrich actuals for the current month and pass a flag to `render_prediction()`:

```python
today = date.today()
current_month = f"{today.year}-{today.month:02d}"
show_actuals = month == current_month
if show_actuals:
    enrich_with_actuals(conn, exp_lines, month, "expenses", account)
    enrich_with_actuals(conn, inc_lines, month, "income", account)
render_prediction(exp_lines, inc_lines, month, fmt, show_actuals=show_actuals)
```

## output.py Change

Add `show_actuals: bool = False` to `render_prediction()`. When `True`:
- Add "Actual (so far)" to `detail_headers`.
- Build the actual cell string using the same logic as `_prediction_df()`.
- Include it in each row.

## Implementation Notes

- The `(X/Y members)` label is informational, not a warning — it signals the data is likely incomplete but does not assert it (the transaction might be legitimately absent, or may arrive later in the month).
- `enrich_with_actuals()` is a separate function, not integrated into `predict_month()`, so `predict_month()` remains pure and testable without a DB connection.
- New tests in `tests/test_predictor.py` should cover: `enrich_with_actuals()` for individual patterns, for group patterns (full payment), and for group patterns (partial payment).
