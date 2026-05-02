# utgiftsanalys

Swedish expense analysis CLI. Imports bank CSV transactions, detects recurring patterns, and predicts future expenses.

## Project Layout

    utgiftsanalys/   # Python package (flat layout)
    spec/            # Work item spec files, one per feature
    tests/           # pytest tests
    data/            # SQLite database lives here (gitignored)

## Package Manager

This project uses [uv](https://docs.astral.sh/uv/). The virtual environment lives in `.venv/` and is managed via `uv sync`.

    # First-time setup
    uv sync --all-extras          # creates .venv and installs all deps incl. dev
    source .venv/bin/activate     # activate the venv (or use `uv run` prefix)

    # Day-to-day
    uv sync --all-extras          # re-sync after pyproject.toml changes
    uv run pytest                 # run tests without activating the venv
    uv run utgiftsanalys --help   # run CLI without activating the venv

uv is installed at `~/.local/bin/uv`. If it's not on PATH, run:

    source ~/.local/bin/env

The lockfile `uv.lock` is committed and pins all transitive dependencies.

## Architecture

- cli.py             — Click commands, no business logic
- db.py              — SQLite schema + CRUD (stdlib sqlite3 only)
- importer.py        — CSV parsing, encoding detection, dedup via import_hash
- calendar_utils.py  — Swedish bank-day calendar + month-boundary rule
- recurring.py       — detect recurring patterns, cadence, cancellation
- predictor.py       — weighted average prediction for a future month
- output.py          — tabulate / CSV rendering

## Key Rules

- Only outgoing transactions (negative Belopp) are analyzed
- Month boundary: first bank day of month M belongs to M-1; second+ to M
- Current analysis month: always use `current_analysis_month()` from `calendar_utils.py` — never `date.today()` directly — so the boundary rule applies everywhere
- Dedup key: SHA-256(booking_date + reference + description + amount)
- Recurring detection requires ≥2 occurrences; gap stddev < 30% of mean gap
- Match key for recurring: both Referens AND Beskrivning must match
- Canceled: last seen > 1.5 × period days ago

## Dependencies

chardet, holidays (Swedish calendar), tabulate, click — all via pyproject.toml
