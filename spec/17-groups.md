# 17 — Transaction Groups

**Status:** [x] done

## Description

Allow transactions to be collected into named groups (e.g. "mortgages", "phone and internet"). A group aggregates one or more `(reference, description)` keys for a single direction (expenses or income), behaves as a single unit during recurring-pattern detection, and carries a hex color used in chart rendering.

## Acceptance Criteria

- A `groups` table and a `group_members` table exist in the SQLite database after `init_db`.
- A group has a unique name, a direction (`expenses` or `income`), and a hex color string.
- Each `(reference, description)` pair belongs to at most one group at a time.
- `build_patterns` treats a group's member transactions, aggregated per `analysis_month`, as a single synthetic stream — producing one `RecurringPattern` (or set of `OneOff`s) per group with the group name as `description` and the group color on the returned dataclass.
- Member `(reference, description)` keys consumed by a group are excluded from the individual per-key loop in `build_patterns`.
- A single-member group works as an alias: it gives the transaction a display name and color with no other behavioral change.
- CLI subcommand group `groups` supports: `list`, `add`, `remove`, `add-member`, `remove-member`.
- The Streamlit UI has a new "Groups" management tab.
- In the Analyze tab, group patterns render as collapsed `st.expander` rows; expanding one shows individual member transactions for the selected month.
- Chart color scales use the group's hex color for that pattern.
- All existing tests pass; new tests cover group CRUD and `build_patterns` with groups.

## Database Schema

Add both tables to the `_DDL` string in `db.py`:

```sql
CREATE TABLE IF NOT EXISTS groups (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    direction TEXT NOT NULL CHECK (direction IN ('expenses', 'income')),
    color     TEXT NOT NULL DEFAULT '#888888'
);

CREATE TABLE IF NOT EXISTS group_members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    reference   TEXT NOT NULL,
    description TEXT NOT NULL,
    UNIQUE (reference, description)
);
```

Enable foreign-key enforcement in `get_connection`:

```python
conn.execute("PRAGMA foreign_keys = ON")
```

## CRUD Functions (db.py)

```python
def fetch_groups(conn, direction=None) -> list[sqlite3.Row]:
    """Return all groups, optionally filtered by direction."""

def fetch_group_members(conn, group_id: int) -> list[sqlite3.Row]:
    """Return (reference, description) rows for a group."""

def insert_group(conn, name: str, direction: str, color: str = "#888888") -> int:
    """Insert a group; return its new id. Raises sqlite3.IntegrityError on duplicate name."""

def delete_group(conn, name: str) -> bool:
    """Delete group by name (cascades to group_members). Returns True if deleted."""

def add_group_member(conn, group_name: str, reference: str, description: str) -> None:
    """Add (reference, description) to the named group.
    Raises sqlite3.IntegrityError if the key is already in any group."""

def remove_group_member(conn, group_name: str, reference: str, description: str) -> bool:
    """Remove (reference, description) from the named group. Returns True if removed."""
```

## RecurringPattern Dataclass (recurring.py)

Add one optional field at the end so existing call sites remain valid:

```python
@dataclass
class RecurringPattern:
    ...
    amounts: list[float]
    color: str | None = None   # set for group patterns
```

## build_patterns Change (recurring.py)

Before the existing per-key loop, insert a group-processing phase:

```python
# --- group phase ---
from .db import fetch_groups, fetch_group_members  # move to top of file
all_groups = fetch_groups(conn, direction=direction)
excluded_keys: set[tuple[str, str]] = set()

# Index all fetched rows by (reference, description)
key_to_rows: dict[tuple[str, str], list] = {}
for row in rows:
    key = (row["reference"] or "", row["description"] or "")
    key_to_rows.setdefault(key, []).append(row)

for grp in all_groups:
    members = fetch_group_members(conn, grp["id"])
    member_keys = {(m["reference"], m["description"]) for m in members}
    excluded_keys |= member_keys

    # Aggregate amounts per analysis_month across all member keys
    month_amounts: dict[str, list[float]] = {}
    all_group_txs: list = []
    for key in member_keys:
        for tx in key_to_rows.get(key, []):
            month_amounts.setdefault(tx["analysis_month"], []).append(tx["amount"])
            all_group_txs.append(tx)

    if not all_group_txs:
        continue

    synthetic_months = sorted(month_amounts)
    synthetic_amounts = [sum(month_amounts[m]) for m in synthetic_months]

    cadence = _detect_cadence(synthetic_months)
    if cadence is None:
        for tx in all_group_txs:
            one_offs.append(OneOff(
                reference=grp["name"], description=grp["name"],
                booking_date=date.fromisoformat(tx["booking_date"]),
                amount=tx["amount"],
            ))
        continue

    classification = _classify_amounts(synthetic_amounts)
    if classification[0] == "fixed":
        amount_type, fixed_amount = "fixed", classification[1]
        min_amount = max_amount = None
    else:
        amount_type, fixed_amount = "variable", None
        _, min_amount, max_amount = classification

    all_dates = sorted(date.fromisoformat(t["booking_date"]) for t in all_group_txs)
    last_seen = max(all_dates)
    period = _PERIOD_DAYS[cadence]
    status = "canceled" if (today - last_seen).days > 1.5 * period else "active"
    end_date = last_seen if status == "canceled" else None

    patterns.append(RecurringPattern(
        reference=grp["name"], description=grp["name"],
        cadence=cadence, amount_type=amount_type,
        fixed_amount=fixed_amount, min_amount=min_amount, max_amount=max_amount,
        start_date=min(all_dates), end_date=end_date,
        status=status, amounts=synthetic_amounts,
        color=grp["color"],
    ))
# --- end group phase ---

# Existing per-key loop — add guard at the top:
for (ref, desc), txs in groups.items():
    if (ref, desc) in excluded_keys:
        continue
    ...
```

## CLI (cli.py)

Add a `groups` command group nested under `main`:

```
utgiftsanalys groups list [--direction expenses|income] [--output table|csv]
utgiftsanalys groups add NAME --direction expenses|income [--color "#RRGGBB"]
utgiftsanalys groups remove NAME [--confirm]
utgiftsanalys groups add-member NAME --reference REF --description DESC
utgiftsanalys groups remove-member NAME --reference REF --description DESC
```

Example session:

```
$ utgiftsanalys groups add "phone and internet" --direction expenses --color "#3498db"
Group 'phone and internet' created.

$ utgiftsanalys groups add-member "phone and internet" \
    --reference "Telia" --description "Telia"
Member added.

$ utgiftsanalys groups list
╭──────────────────────┬───────────┬──────────╮
│ Name                 │ Direction │ Color    │
├──────────────────────┼───────────┼──────────┤
│ phone and internet   │ expenses  │ #3498db  │
╰──────────────────────┴───────────┴──────────╯
```

Add `render_groups(groups, output)` to `output.py`.

## Streamlit UI (ui.py)

### New "Groups" tab (7th tab)

`_tab_groups(conn, account)`:
- Left column: table of existing groups with a **Delete** button per row.
- Right column: "Create group" form — `st.text_input` for name, `st.selectbox` for direction, `st.color_picker` for color, submit button calling `insert_group`.
- Below the table: one `st.expander` per group titled with the group name, containing:
  - A table of current members with a **Remove** button per row.
  - A `st.multiselect` populated from all known `(reference, description)` pairs for that direction (fetched once via `fetch_transactions`). An **Add members** button calls `add_group_member` for each selection.
- After any mutation call `st.cache_data.clear()` to invalidate cached pattern results.

### Analyze tab changes

In `_tab_analyze`, for each `RecurringPattern` with a non-None `color` field:
- Render an `st.expander` showing the group name, cadence, and predicted amount (collapsed by default).
- Inside the expander: a dataframe of individual member transactions for the selected month (fetched via `fetch_transactions(conn, month=month)`; filter to keys that are members of this group).

Non-group patterns continue to render in the existing flat `st.dataframe`.

### Chart color changes

Where charts encode a per-pattern series, derive an explicit color domain/range from patterns that carry a color:

```python
colored = [(p.description, p.color) for p in patterns if p.color]
if colored:
    domain, color_range = zip(*colored)
    color_enc = alt.Color("series:N",
        scale=alt.Scale(domain=list(domain), range=list(color_range)))
```

Patterns without a color continue to use Altair's default scheme.

## Implementation Notes

- `PRAGMA foreign_keys = ON` must be set in `get_connection` (not just `init_db`) because it is a per-connection setting.
- The `UNIQUE (reference, description)` constraint on `group_members` enforces the one-group-per-key invariant at the DB level. `add_group_member` should surface an `sqlite3.IntegrityError` as a `click.UsageError` ("that transaction key is already in a group") in the CLI.
- `ON DELETE CASCADE` on `group_members.group_id` means deleting a group automatically removes its members — no manual cleanup needed.
- The internal `groups` dict variable in the original `build_patterns` loop (`groups: dict[tuple[str,str], list] = {}`) should be renamed to `key_groups` to avoid shadowing the new `groups` CRUD import.
- `chart_data.py` functions do not need changes; color application is a UI concern handled in `ui.py`.
- Migration: existing databases need no schema change other than the two new tables, which are added via `IF NOT EXISTS`.
