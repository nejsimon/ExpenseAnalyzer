# 21 — Grouping Toggle in Analyze and Predict

**Status:** [ ] pending

## Description

The Analyze and Predict tabs always show transactions in grouped mode — group members are aggregated into a single row. Sometimes it is useful to see the underlying individual merchants instead. This spec adds a toggle that switches between grouped mode (default, current behaviour) and flat mode (all transactions shown as individual merchants, group aggregation disabled).

## Acceptance Criteria

- A "Group transactions" checkbox appears in both the Analyze and Predict tabs, checked by default.
- When unchecked, Analyze and Predict show individual merchant patterns; no group expanders appear.
- When unchecked, group member merchants appear in the flat pattern table just like any other individual merchant.
- The CLI `analyze` and `predict` commands gain a `--flat` flag that activates flat mode.
- Existing behaviour is unchanged when the checkbox is checked / `--flat` is absent.
- `uv run mypy utgiftsanalys/` exits 0. `uv run ruff check utgiftsanalys/` exits 0. All existing tests pass.

## `build_patterns()` Change (recurring.py)

Add a `grouped: bool = True` parameter:

```python
def build_patterns(
    conn: sqlite3.Connection,
    reference_date: date | None = None,
    account: str | None = None,
    direction: str = "expenses",
    grouped: bool = True,
) -> tuple[list[RecurringPattern], list[OneOff]]:
```

When `grouped=False`, skip the entire group phase. Do not populate `excluded_keys`; let every (reference, description) key fall through to the per-key phase, where they are detected as individual patterns. The group phase block becomes:

```python
if grouped:
    for grp in fetch_groups(conn, direction=direction):
        ...  # unchanged
```

No other changes to `build_patterns()`.

## UI Changes (ui.py)

### `_tab_analyze()`

Add immediately after the month/deposits controls:

```python
grouped = st.checkbox("Group transactions", value=True, key="analyze_grouped")
```

Pass `grouped` to both `build_patterns()` calls:

```python
exp_patterns, exp_one_offs = build_patterns(conn, account=account, direction="expenses", grouped=grouped)
inc_patterns, inc_one_offs = build_patterns(conn, account=account, direction="income", grouped=grouped)
```

When `grouped=False`, `build_patterns` returns no group patterns, so `_render_recurring_section` receives no group rows — the expander block is naturally empty and only the flat individual table is shown. No changes needed to `_render_recurring_section`.

### `_tab_predict()`

Add immediately after the month selector:

```python
grouped = st.checkbox("Group transactions", value=True, key="predict_grouped")
```

Pass `grouped` to both `build_patterns()` calls:

```python
exp_patterns, _ = build_patterns(conn, account=account, direction="expenses", grouped=grouped)
inc_patterns, _ = build_patterns(conn, account=account, direction="income", grouped=grouped)
```

## CLI Changes (cli.py)

### `analyze` command

Add a `--flat` flag:

```python
@click.option("--flat", is_flag=True, default=False, help="Show individual merchants instead of groups.")
def analyze(ctx, month, fmt, deposits_only, flat):
    ...
    exp_patterns, exp_one_offs = build_patterns(conn, account=account, direction="expenses", grouped=not flat)
    inc_patterns, inc_one_offs = build_patterns(conn, account=account, direction="income", grouped=not flat)
```

### `predict` command

Add the same `--flat` flag:

```python
@click.option("--flat", is_flag=True, default=False, help="Show individual merchants instead of groups.")
def predict(ctx, month, fmt, flat):
    ...
    exp_patterns, _ = build_patterns(conn, account=account, direction="expenses", grouped=not flat)
    inc_patterns, _ = build_patterns(conn, account=account, direction="income", grouped=not flat)
```

## Implementation Notes

- No changes to `predict_month()`, `render_prediction()`, `render_recurring_summary()`, or `output.py` — they are already agnostic about whether patterns come from groups or individuals.
- No changes to `chart_data.py` or `stats.py` — those always use grouped mode and that is correct.
- The flat mode for `analyze` does not change one-off filtering; one-off detection also runs on individual keys when `grouped=False`, so group member one-offs appear in the one-offs section.
- New tests in `tests/test_recurring.py` should cover: `build_patterns(grouped=False)` returns group member keys as individual patterns, not as a group pattern.
