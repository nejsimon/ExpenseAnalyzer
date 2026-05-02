# Spec 24 — Group Color Improvements

**Status:** [x] done

## Problem

Group colors are exposed only as raw hex strings — in the expander header and as a "Color" text column in data tables. The Color column shows ugly hex text (or nothing on Streamlit 1.56.0 which lacks `ColorColumn`). There is no way to edit a group's color after creation.

## Changes

1. **Row background coloring** — drop the "Color" column from the Analyze and Predict tables; apply row backgrounds with auto-contrasting text via `pandas.Styler`. Ungrouped rows inherit the theme background.
2. **WCAG contrast text** — `_contrast_color(hex)` uses the WCAG relative-luminance formula to choose `#000000` or `#ffffff`; threshold at luminance 0.179 (equal-contrast crossover).
3. **Dark/light mode** — ungrouped rows have no inline style (inherit theme); colored rows carry explicit `background-color` + `color`, readable in both modes.
4. **Edit group color** — a `st.color_picker` inside each group expander allows editing the color at any time; calls new `update_group_color()` DB function.
5. **Cleaner expander header** — raw hex removed; header shows `name  ·  direction` only.
6. **Remove `_make_color_col_config` / `_COLOR_COL_CONFIG`** — no longer needed.

## New DB function

```python
def update_group_color(conn, name, color) -> bool
```

`UPDATE groups SET color = ? WHERE name = ?`. Returns `True` if the group was found.

## New UI helpers

```python
def _contrast_color(hex_color: str) -> str
def _style_by_color(df: pd.DataFrame, color_map: dict[str, str]) -> pd.io.formats.style.Styler
```

`_style_by_color` applies a row-level style function: rows whose `"Merchant"` key is in `color_map` get `background-color` + contrasting `color`; all others get `""` to inherit the theme.
