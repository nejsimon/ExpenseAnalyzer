# 06 — Prediction

**Status:** [x] done

## Description

Predict the total outgoing expenses for a given future month by summing the expected recurring transactions.

## Acceptance Criteria

- `utgiftsanalys predict --month 2026-06` shows a table of expected recurring transactions with predicted amounts and a total.
- Only active (non-canceled) patterns are included.
- For fixed-sum patterns, the exact `fixed_amount` is used.
- For variable-sum patterns, the predicted amount is a linearly-weighted historical average (newer = higher weight).
- The correct cadence-to-month logic is applied (quarterly patterns only appear every 3rd month, etc.).

## Cadence Hit Logic

A pattern with `cadence` and `start_date` is expected in `target_month` if:

- `monthly`: always (every month).
- `quarterly`: `(target_month_index - start_month_index) % 3 == 0` where month index = `year * 12 + month`.
- `yearly`: `target_month == month(start_date)` (same calendar month).

## Weighted Average Formula

For variable-sum pattern with historical amounts `[a_1, a_2, ..., a_N]` (oldest → newest, as absolute values):

```
weight_i = i   (i = 1 for oldest, N for newest)
predicted = sum(i * a_i for i in 1..N) / (N * (N + 1) / 2)
```

## Output

```
Merchant          Cadence    Predicted
──────────────────────────────────────
Lf Uppsala        monthly      195.00
Spotify           monthly      119.00
Electric bill     monthly      612.50  (variable, range 400–820)
──────────────────────────────────────
Total                        926.50
```
