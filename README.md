# utgiftsanalys

Swedish bank transaction analyser. Import CSV exports from your bank, detect recurring expenses and income, and predict future months.

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
uv run utgiftsanalys --help
uv run utgiftsanalys import transactions.csv
uv run utgiftsanalys analyze
uv run utgiftsanalys predict --month 2026-06
uv run utgiftsanalys stats
```

The database is stored at `data/utgiftsanalys.db` by default. Override with the `UTGIFTSANALYS_DB` environment variable or the `--db` flag.

## Run tests

```bash
uv run pytest
```

## Docker

Build:

```bash
docker build -t utgiftsanalys .
```

Run (mounts `./data` for database persistence):

```bash
docker run -p 8501:8501 -v $PWD/data:/data utgiftsanalys
```

Opens at http://localhost:8501.
