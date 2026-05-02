# Spec 26 — Trend Line in Predicted vs Actual Chart

**Status:** [x] done

## Change

Added a linear trend line to the "Predicted vs actual expenses" chart (Chart 3 in the Charts tab).

- Computed by simple linear regression over the historical actual expenses (complete months only — before the current analysis month).
- Extended one step to the current month position if it is in the selected range (projection, not based on actual data).
- Fewer than 2 complete months in range: trend is silently omitted.
- Rendered as a dashed line (`strokeDash` encoding) so it is visually distinct from Actual (solid) and Predicted (short dash).
- "Trend" appears as its own entry in the chart legend.
- No new dependencies — regression is pure Python.
