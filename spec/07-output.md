# 07 — Output Rendering

**Status:** [x] done

## Acceptance Criteria

- Default output (`--output table`) renders a rounded table via `tabulate`.
- `--output csv` writes valid CSV to stdout (can be piped or redirected).
- Amounts are formatted to 2 decimal places.
- All `render_*` functions accept `fmt: str` with values `"table"` or `"csv"`.

## Output Functions

| Function                  | Used by         | Description                          |
|---------------------------|-----------------|--------------------------------------|
| `render_import_result`    | `import` cmd    | "Inserted N, skipped M"              |
| `render_recurring_summary`| `analyze` cmd   | Recurring patterns + one-offs table  |
| `render_prediction`       | `predict` cmd   | Predicted amounts + total            |

## Table Format

Use `tabulate(data, headers=headers, tablefmt="rounded_outline")` for the default table format.

## CSV Format

Use `csv.writer(sys.stdout)` with a header row followed by data rows. Amounts as plain floats (e.g. `195.00`).

## `analyze` Table Layout

```
Merchant          Cadence    Amount         Start       Status
────────────────────────────────────────────────────────────────
Lf Uppsala        monthly    195.00 (fixed) 2025-01     active
Electric bill     monthly    400–820 (var)  2024-01     active
Dentist           yearly     1200.00 (fixed)2024-03     canceled (last: 2025-03)

One-offs
──────────────────────────────────
ICA Maxi          2026-04-05  -1243.50
Systembolaget     2026-04-12   -349.00
```
