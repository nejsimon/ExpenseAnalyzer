# 05 — Recurring Transaction Detection

**Status:** [x] done

## Description

Analyze imported transactions to identify recurring patterns. Output a list of patterns with cadence, amount type, start/end dates, and active/canceled status.

## Acceptance Criteria

- A merchant appearing ~monthly is classified as `monthly`.
- Quarterly (every ~3 months) and yearly patterns are detected.
- A pattern where all amounts are within tolerance is classified as `fixed`.
- A pattern with varying amounts is classified as `variable`; min and max are recorded.
- A pattern not seen for > 1.5× its period is marked `canceled` with `end_date`.
- Single-occurrence merchants are classified as one-offs (not recurring).
- Transactions are matched by **both** `reference` AND `description` (both must match).

## Detection Algorithm

1. Filter to outgoing transactions (`amount < 0`).
2. Group by `(normalize(reference), normalize(description))`.
3. For each group with ≥2 occurrences:
   - Sort occurrence dates.
   - Compute gaps (days) between consecutive dates.
   - `mean_gap = mean(gaps)`
   - Classify cadence:
     - `25 ≤ mean_gap ≤ 35` → `monthly`
     - `80 ≤ mean_gap ≤ 100` → `quarterly`
     - `330 ≤ mean_gap ≤ 400` → `yearly`
     - Otherwise → one-off
   - Require `stddev(gaps) < 0.30 × mean_gap` (consistency).
4. Amount classification: `stddev(amounts) < 5.0` or `stddev(amounts) / mean(amounts) < 0.02` → `fixed`; else `variable`.
5. Price increase handling: if the last 3+ occurrences share a new fixed amount that differs from the historical mean, update `fixed_amount` to the new value.
6. Cancellation: `period_days` = 30 / 91 / 365 for monthly / quarterly / yearly. If `(today - last_seen).days > 1.5 × period_days` → `canceled`, `end_date = last_seen`.

## Output Fields per Pattern

| Field        | Type    | Description                          |
|--------------|---------|--------------------------------------|
| description  | str     | Normalized merchant name             |
| reference    | str     | Normalized reference                 |
| cadence      | str     | monthly / quarterly / yearly         |
| amount_type  | str     | fixed / variable                     |
| fixed_amount | float?  | Set if fixed                         |
| min_amount   | float?  | Set if variable                      |
| max_amount   | float?  | Set if variable                      |
| start_date   | date    | First occurrence                     |
| end_date     | date?   | Last occurrence if canceled          |
| status       | str     | active / canceled                    |
