# Spec 25 — Current Month Breakpoint

**Status:** [x] done

## Problem

The bank-day month-boundary rule (first bank day of month M belongs to M-1) was only applied when importing transactions. Every UI tab and CLI command computed the "current month" as a raw calendar month from `date.today()`, ignoring the rule.

## Changes

- **`calendar_utils.py`**: added `current_analysis_month(reference: date | None = None) -> str` — calls `get_analysis_month(reference or date.today())`.
- **`ui.py`**: three locations (`_tab_analyze`, `_tab_predict`, `_tab_charts`) now call `current_analysis_month()` instead of building the month string from `date.today()`.
- **`cli.py`**: `analyze` and `predict` default months now use `current_analysis_month()`.
- **`CLAUDE.md`**: added a rule: always use `current_analysis_month()` from `calendar_utils.py`, never `date.today()` directly.
