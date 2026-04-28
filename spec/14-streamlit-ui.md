# 14 — Streamlit UI

**Status:** [x] done

## Description

Replace the FastAPI layer with a Streamlit browser UI that exposes all CLI analysis features in a browser. The UI calls business logic functions directly — no REST intermediary.

## Acceptance Criteria

- `streamlit run utgiftsanalys/ui.py` starts the server.
- All CLI analysis features (import, analyze, predict, stats, accounts) are accessible in the browser.
- A sidebar account selector filters all tabs to a specific account (or "All accounts").
- Importing a CSV shows inserted/skipped counts and any hole-detection warnings.
- Unrecognized CSV headers show `st.error`; ambiguous adapter shows a selectbox to resolve.
- `utgiftsanalys/app.py` and `tests/test_app.py` are deleted.
- `api` optional dep group and `httpx` dev dep are removed from `pyproject.toml`.

## UI Layout

### Sidebar
- Account selector — dropdown populated from `fetch_accounts(conn)`; first option "All accounts" (passes `account=None`).
- DB path shown as info text (from `UTGIFTSANALYS_DB` env var, or default).

### Tabs: Import | Analyze | Predict | Stats | Accounts

**Import**
- `st.file_uploader` accepting `.csv` files.
- Adapter selector: dropdown listing `ADAPTERS` names plus "Auto-detect" (default).
- On upload: write bytes to `tempfile.NamedTemporaryFile`, call `import_file`, display inserted/skipped counts and warnings via `st.success` / `st.warning` / `st.error`.
- On `AmbiguousAdapterError`: show a second selectbox so the user can pick and retry.

**Analyze**
- Month selectbox populated from `fetch_months(conn)`; default = current month.
- "Deposits only" checkbox.
- Expenses section: recurring patterns `st.dataframe` + one-offs `st.dataframe`.
- Income section: recurring patterns `st.dataframe` + one-offs `st.dataframe`.
- One-offs filtered to the selected month.

**Predict**
- Month selectbox (list of upcoming 12 months); default = `next_month(date.today())`.
- Expense prediction table, income prediction table.
- Net summary (income total − expense total) shown as a metric.

**Stats**
- Expense stats table, income stats table — same columns as CLI `render_stats`.

**Accounts**
- `st.dataframe` with account number and transaction count.

## Implementation Notes

- New file `utgiftsanalys/ui.py`.
- Add optional dep group: `ui = ["streamlit>=1.35"]` in `pyproject.toml`.
- DB connection: open at the top of each Streamlit run using `get_connection` + `init_db`; close at end. Use `st.cache_resource` for the connection to avoid re-opening on every rerun.
- `UTGIFTSANALYS_DB` env var → default `DEFAULT_DB_PATH` from `db.py`.
- Reuse existing functions: `build_patterns`, `predict_month`, `compute_stats`, `fetch_accounts`, `fetch_months`, `import_file`, `ADAPTERS`, `AmbiguousAdapterError`, `next_month`.
- Do not reuse `output.py` render functions (they write to stdout); build dataframes directly from the data objects.
