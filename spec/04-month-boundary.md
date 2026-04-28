# 04 — Month Boundary Rule

**Status:** [x] done

## Description

Compute `analysis_month` for each transaction using the Swedish bank-day calendar. The breakpoint between month M-1 and month M is the **second bank day** of month M.

## Acceptance Criteria

- A transaction on the first bank day of month M is assigned to month M-1.
- A transaction on the second (or later) bank day of month M is assigned to month M.
- Swedish public holidays are excluded from bank days (e.g. Midsommarafton, Easter Monday).
- A transaction on January 1 (or first bank day of January) is assigned to December of the prior year.
- `swedish_bank_days(2026, 1)` returns only weekdays excluding New Year's Day.

## Rule Definition

```
analysis_month(booking_date d):
    bank_days = swedish_bank_days(d.year, d.month)   # sorted list
    first_bd  = bank_days[0]
    if d <= first_bd:
        return (d.year, d.month) - 1 month
    else:
        return (d.year, d.month)
```

## Implementation Notes

- `swedish_bank_days(year, month)`: generate all days in month, keep Mon–Fri, remove dates in `holidays.Sweden(years=[year])`.
- The `holidays` library returns a dict; `date in holidays_dict` is O(1).
- Month subtraction: if `month == 1` return `(year-1, 12)` else `(year, month-1)`.
- Return value of `get_analysis_month` is a string `"YYYY-MM"`.
