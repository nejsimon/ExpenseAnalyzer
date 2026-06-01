# Expense Analyzer

Bank transaction analyser. Import CSV exports from your bank, detect recurring expenses and income, and predict future months.

## Setup

```bash
uv sync --extra ui
```

## Run the UI

```bash
streamlit run utgiftsanalys/ui.py
```

Opens at http://localhost:8501.

## Run the CLI

```bash
uv run expense-analyzer --help
uv run expense-analyzer import transactions.csv
uv run expense-analyzer analyze
uv run expense-analyzer predict --month 2026-06
uv run expense-analyzer stats
```

The database is stored at `data/utgiftsanalys.db` by default. Override with the `EXPENSE_ANALYZER_DB` environment variable or the `--db` flag.

## Run tests

```bash
uv run pytest
```

## Docker

Build:

```bash
docker build -t expense-analyzer .
```

Run (mounts `./data` for database persistence):

```bash
docker run -p 8501:8501 -v $PWD/data:/data expense-analyzer
```

Opens at http://localhost:8501.
