# 22 — Per-Group "Exclude from Prediction"

**Status:** [x] done

## Description

Some groups contain transactions that are not relevant to forward-looking predictions — one-time purchases that happen to repeat, manually managed expenses, or anything the user does not want to see in the predict output. This spec adds an `exclude_from_prediction` boolean to each group. When set, the group's pattern is omitted from `predict_month()` output and from the yearly stats predictions. The analyze tab is unaffected.

## Acceptance Criteria

- Each group has an `exclude_from_prediction` flag (default `False`).
- Groups with `exclude_from_prediction = True` do not appear in the Predict tab or CLI `predict` output.
- Groups with `exclude_from_prediction = True` do not contribute to `compute_stats()` predictions.
- The Groups tab in the UI shows a toggle per group to set this flag.
- The CLI gains `groups set-predict-exclude <name> --exclude / --no-exclude`.
- Existing DBs without the column are migrated automatically on next `init_db()`.
- `uv run mypy utgiftsanalys/` exits 0. `uv run ruff check utgiftsanalys/` exits 0. All existing tests pass.

## DB Change (db.py)

### Schema

Add the column to the `CREATE TABLE groups` DDL:

```sql
CREATE TABLE IF NOT EXISTS groups (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL UNIQUE,
    direction               TEXT NOT NULL CHECK (direction IN ('expenses', 'income')),
    color                   TEXT NOT NULL DEFAULT '#888888',
    exclude_from_prediction INTEGER NOT NULL DEFAULT 0
);
```

### Migration

Add a migration step in `init_db()`, after `executescript(_DDL)`, to add the column to existing databases:

```python
try:
    conn.execute(
        "ALTER TABLE groups ADD COLUMN exclude_from_prediction INTEGER NOT NULL DEFAULT 0"
    )
    conn.commit()
except sqlite3.OperationalError:
    pass  # column already exists
```

### New DB function

```python
def set_group_exclude(conn: sqlite3.Connection, name: str, exclude: bool) -> bool:
    """Set exclude_from_prediction for a group. Returns True if the group was found."""
    cursor = conn.execute(
        "UPDATE groups SET exclude_from_prediction = ? WHERE name = ?",
        (1 if exclude else 0, name),
    )
    conn.commit()
    return cursor.rowcount == 1
```

## `RecurringPattern` Change (recurring.py)

Add a field with a default so all existing callers are unaffected:

```python
@dataclass
class RecurringPattern:
    ...
    color: str | None = None
    exclude_from_prediction: bool = False
```

In `build_patterns()`, populate this field for group patterns:

```python
patterns.append(
    RecurringPattern(
        ...
        color=grp["color"],
        exclude_from_prediction=bool(grp["exclude_from_prediction"]),
    )
)
```

Individual (non-group) patterns always leave `exclude_from_prediction` as its default `False`.

## `predict_month()` Change (predictor.py)

Add one extra filter:

```python
for p in patterns:
    if p.status != "active":
        continue
    if p.exclude_from_prediction:
        continue
    ...
```

This makes the filter apply to the stats predictions as well, since `monthly_with_predictions()` in `chart_data.py` calls `predict_month()`.

## UI Changes (ui.py)

### Groups tab (`_tab_groups()`)

Import `set_group_exclude` from `.db`. For each group expander, add a toggle after the existing delete button:

```python
excluded = bool(grp["exclude_from_prediction"])
new_val = st.toggle(
    "Exclude from predictions",
    value=excluded,
    key=f"excl_{grp['id']}",
)
if new_val != excluded:
    set_group_exclude(conn, grp["name"], new_val)
    st.rerun()
```

## CLI Changes (cli.py)

Import `set_group_exclude` from `.db`. Add a new subcommand under `groups_cmd`:

```python
@groups_cmd.command("set-predict-exclude")
@click.argument("name")
@click.option("--exclude/--no-exclude", default=True, help="Exclude this group from predictions.")
@click.pass_context
def groups_set_predict_exclude(ctx: click.Context, name: str, exclude: bool) -> None:
    """Exclude or include a group in predictions."""
    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    found = set_group_exclude(conn, name, exclude)
    conn.close()
    if found:
        status = "excluded from" if exclude else "included in"
        click.echo(f"Group '{name}' is now {status} predictions.")
    else:
        click.echo(f"No group named '{name}'.", err=True)
```

## Implementation Notes

- The flag only affects predictions. `build_patterns()`, `render_recurring_summary()`, and the analyze tab all see the group unchanged — exclusion is a prediction-only concept.
- `compute_stats()` is unaffected structurally; it benefits from the filter automatically via `predict_month()`.
- New tests in `tests/test_predictor.py`: a pattern with `exclude_from_prediction=True` does not appear in `predict_month()` output. New test in `tests/test_groups.py`: `set_group_exclude()` round-trips correctly; `build_patterns()` returns a pattern with `exclude_from_prediction=True` when the group has the flag set.
