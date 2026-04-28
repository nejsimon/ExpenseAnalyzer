# 03 — Database

**Status:** [x] done

## Description

SQLite schema, connection management, and raw CRUD helpers. No ORM — plain `sqlite3` from the standard library.

## Acceptance Criteria

- `data/utgiftsanalys.db` is created on first run if it does not exist.
- `init_db` is idempotent (`CREATE TABLE IF NOT EXISTS`).
- `INSERT OR IGNORE` on `import_hash` prevents duplicate rows.
- `fetch_transactions(conn, month=None, outgoing_only=True)` returns the correct subset.

## Schema

```sql
CREATE TABLE IF NOT EXISTS transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    row_number       INTEGER,
    clearing         TEXT,
    account          TEXT,
    product          TEXT,
    currency         TEXT,
    booking_date     TEXT,
    transaction_date TEXT,
    value_date       TEXT,
    reference        TEXT,
    description      TEXT,
    amount           REAL,
    balance          REAL,
    import_hash      TEXT UNIQUE,
    analysis_month   TEXT
);
```

## Implementation Notes

- `get_connection(db_path)`: returns `sqlite3.connect(db_path)` with `conn.row_factory = sqlite3.Row` and `PRAGMA journal_mode=WAL`.
- Default `db_path` is `./data/utgiftsanalys.db`; configurable via `--db` CLI option.
- `fetch_transactions` filters `amount < 0` when `outgoing_only=True`.
- `fetch_months(conn)` returns sorted list of distinct `analysis_month` strings.
