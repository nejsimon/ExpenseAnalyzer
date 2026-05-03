# Spec 27 — Quarterly Phase Anchor Fix

**Status:** [x] done

## Problem

`_hits_month()` in `predictor.py` used `start_date` (first booking date) as the phase anchor
for quarterly and yearly cadences. If the pattern's first occurrence falls in a different
quarterly cycle than recent occurrences, the phase drifts and predictions land in the wrong month.

Example: U A VA has `start_date` = April 2024 and `last_analysis_month` = 2026-03. April 2026
is exactly 24 months (8 quarters) from April 2024 → incorrectly predicted. Actual next hit
anchored to March 2026 is June 2026.

## Fix

- Added `last_analysis_month: str = ""` to `RecurringPattern` (already added in a prior session).
- Populated `last_analysis_month` in `build_patterns()`:
  - Individual patterns: `max(t["analysis_month"] for t in txs_sorted)`
  - Group patterns: `max(synthetic_months)`
- `_hits_month()` uses `last_analysis_month` as anchor when set, falling back to `start_date`
  when the field is empty (backwards compatibility with manually constructed patterns in tests).

## Files changed

- `utgiftsanalys/recurring.py` — populate `last_analysis_month` in `build_patterns()`
- `utgiftsanalys/predictor.py` — use `last_analysis_month` as phase anchor in `_hits_month()`
- `tests/test_predictor.py` — two new tests covering the anchor fix
