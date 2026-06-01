# Spec 28 — Group Icons

**Status:** [x] done

## Goal

Allow each group to have an optional icon (emoji) that appears in all list views and chart legends, making it faster to scan groups visually.

## Icon library

Use **emoji** — zero new dependencies, renders natively in browsers and Streamlit, works in Altair SVG chart legends, and travels in plain text (DB storage, copy/paste).

A curated palette of ~50 emoji relevant to personal finance is hardcoded in the app. The full Unicode emoji set is intentionally excluded to keep the picker focused.

### Palette (grouped by category)

| Category | Emoji |
|---|---|
| Home | 🏠 💡 🔥 🌊 🛠️ 🔑 |
| Transport | 🚗 🚌 🚲 ✈️ 🚂 ⛽ |
| Food | 🛒 🍽️ ☕ 🍕 🥤 🥦 |
| Health | 💊 🏥 💪 🧘 🦷 👁️ |
| Entertainment | 📺 🎮 🎵 🎬 📚 🎭 |
| Tech / comms | 📱 💻 📶 🖥️ |
| Finance | 💰 🏦 💳 📈 🏧 |
| Personal care | 👕 💇 🐕 🐈 🧴 |
| Education | 🎓 📐 |
| Work / income | 💼 👔 📊 |
| Misc | 🎁 🧾 ✈️ 🌍 |

## Schema change

```sql
ALTER TABLE groups ADD COLUMN icon TEXT DEFAULT NULL;
```

Run as a migration in `init_db()` alongside the existing `exclude_from_prediction` and `is_offset` migrations.

## Code changes

### `expense_analyzer/db.py`

- Add `icon TEXT DEFAULT NULL` to the `groups` `CREATE TABLE` statement.
- Add migration in `init_db()`.
- Add `update_group_icon(conn, name: str, icon: str | None) -> bool`.

### `expense_analyzer/ui.py`

**Groups tab (`_tab_groups`):**
- Below the color picker, add an icon picker: a grid of buttons (one per emoji in the palette) plus a "none" option. Clicking one calls `update_group_icon` and reruns.
- Show the currently selected icon next to the group name in the expander header, e.g. `🚗 Car`.

**Display helper:**
```python
def _group_label(name: str, icon: str | None) -> str:
    return f"{icon} {name}" if icon else name
```

Use `_group_label` everywhere a group name is rendered as a string:
- Expander header in Groups tab
- `_pattern_df()` — Merchant column for group patterns (detected via `p.color is not None`, which already identifies group rows)
- `_prediction_df()` — Merchant column for group lines (same detection via `line.color`)
- Chart data: before charting in `_tab_charts()`, remap group names in the dataframe using a `name → label` dict built from `fetch_groups(conn)`

**Chart legend:**
In `_tab_charts()`, build `icon_map: dict[str, str]` from `{grp["name"]: _group_label(grp["name"], grp["icon"]) for grp in fetch_groups(conn)}` and apply it to the `group` column of the breakdown dataframes before creating the Altair charts. Since Altair uses the `group` field as both the domain key and the legend label, renaming the column values is enough.

### `expense_analyzer/chart_data.py`

No changes — chart_data returns raw group names; icon remapping is a UI-layer concern.

### `tests/test_groups.py`

Add tests for `update_group_icon`: round-trip, missing group returns False, None clears icon.

## Interaction design

- Icon picker is shown in the group expander below the color picker.
- Palette rendered as a compact grid (e.g. `st.columns(10)` with one emoji button per cell).
- A "✕ none" button clears the icon.
- No icon is a valid state — groups without icons display name-only, unchanged from today.

## Verification

- `uv run pytest` passes.
- `uv run mypy expense_analyzer/` exits 0.
- `uv run ruff check expense_analyzer/` exits 0.
- Manual: assign icon 🚗 to a group → icon appears in Analyze table, Predict table, Charts legend, and Groups expander header.
- Manual: clear icon → group reverts to name-only display everywhere.
