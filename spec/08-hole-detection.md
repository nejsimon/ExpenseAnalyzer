# 08 — Hole Detection

**Status:** [x] done

## Description

When importing a CSV, detect months that were likely omitted from the export. Warn the user and continue importing. Two complementary checks are run.

## Acceptance Criteria

- Importing a CSV that spans Jan–Mar but has no transactions in Feb prints a warning naming February as a suspected hole.
- A merchant present in both M-1 and M+1 but absent in M triggers a per-merchant warning for M.
- Warnings are printed to stderr; import proceeds normally.
- If no holes are detected, no warning is printed.
- Hole warnings include the affected month(s) and, for merchant-level holes, the merchant name.

## Detection Algorithm

Run after all rows from the file have been normalized (before DB insert, working on the in-memory batch):

### Check 1 — Sequence gaps

1. Collect the set of distinct `analysis_month` values in the import batch.
2. For each consecutive pair of months `(prev, next)` in sorted order, if the calendar distance between them is more than 1 month, all intermediate months are flagged as sequence gaps.
3. Warn: `"Warning: month(s) {gaps} appear to be missing from the import (no transactions found)."`

### Check 2 — Merchant disappearance

1. Group imported transactions (outgoing only) by `(reference, description)`.
2. For each merchant group, collect the set of `analysis_month` values.
3. For each consecutive month triple `(M-1, M, M+1)` where the merchant is present in M-1 AND M+1 but absent in M: flag this as a merchant-level hole.
4. Warn: `"Warning: '{merchant}' present in {M-1} and {M+1} but missing in {M} — possible gap."`

## Implementation Notes

- `detect_holes(batch: list[dict]) -> list[str]` in `importer.py` — returns list of warning strings.
- Call `detect_holes` on the normalized batch before inserting rows; print warnings to `sys.stderr`.
- Check 2 only considers outgoing transactions (`amount < 0`) to avoid salary-timing noise.
- Merchant identity: `(reference, description)` pair (same as recurring detection).
- Month arithmetic helper: `add_months(ym: str, n: int) -> str` returns YYYY-MM offset by `n` months.
