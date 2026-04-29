import sqlite3
from pathlib import Path
from typing import TypedDict


class TransactionDict(TypedDict):
    row_number:       int | None
    clearing:         str | None
    account:          str | None
    product:          str | None
    currency:         str | None
    booking_date:     str
    transaction_date: str | None
    value_date:       str | None
    reference:        str | None
    description:      str | None
    amount:           float
    balance:          float | None
    import_hash:      str
    analysis_month:   str

DEFAULT_DB_PATH = str(Path(__file__).parent.parent / "data" / "utgiftsanalys.db")

_DDL = """
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

CREATE TABLE IF NOT EXISTS groups (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    direction TEXT NOT NULL CHECK (direction IN ('expenses', 'income')),
    color     TEXT NOT NULL DEFAULT '#888888'
);

CREATE TABLE IF NOT EXISTS group_members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    reference   TEXT NOT NULL,
    description TEXT NOT NULL,
    UNIQUE (reference, description)
);
"""


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    conn.commit()


def insert_transaction(conn: sqlite3.Connection, tx: TransactionDict) -> bool:
    """Returns True if inserted, False if skipped (duplicate)."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO transactions
            (row_number, clearing, account, product, currency,
             booking_date, transaction_date, value_date,
             reference, description, amount, balance,
             import_hash, analysis_month)
        VALUES
            (:row_number, :clearing, :account, :product, :currency,
             :booking_date, :transaction_date, :value_date,
             :reference, :description, :amount, :balance,
             :import_hash, :analysis_month)
        """,
        tx,
    )
    return cursor.rowcount == 1


def fetch_transactions(
    conn: sqlite3.Connection,
    month: str | None = None,
    outgoing_only: bool = True,
    incoming_only: bool = False,
    account: str | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list[str] = []
    if outgoing_only:
        clauses.append("amount < 0")
    elif incoming_only:
        clauses.append("amount > 0")
    if month:
        clauses.append("analysis_month = ?")
        params.append(month)
    if account:
        clauses.append("account = ?")
        params.append(account)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return conn.execute(
        f"SELECT * FROM transactions {where} ORDER BY booking_date",
        params,
    ).fetchall()


def fetch_months(conn: sqlite3.Connection, account: str | None = None) -> list[str]:
    clauses: list[str] = []
    params: list[str] = []
    if account:
        clauses.append("account = ?")
        params.append(account)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT DISTINCT analysis_month FROM transactions {where} ORDER BY analysis_month",
        params,
    ).fetchall()
    return [r[0] for r in rows]


def fetch_groups(
    conn: sqlite3.Connection,
    direction: str | None = None,
) -> list[sqlite3.Row]:
    """Return all groups, optionally filtered by direction, ordered by name."""
    if direction:
        return conn.execute(
            "SELECT * FROM groups WHERE direction = ? ORDER BY name", (direction,)
        ).fetchall()
    return conn.execute("SELECT * FROM groups ORDER BY name").fetchall()


def fetch_group_members(
    conn: sqlite3.Connection,
    group_id: int,
) -> list[sqlite3.Row]:
    """Return (reference, description) rows for a group."""
    return conn.execute(
        "SELECT * FROM group_members WHERE group_id = ?", (group_id,)
    ).fetchall()


def insert_group(
    conn: sqlite3.Connection,
    name: str,
    direction: str,
    color: str = "#888888",
) -> int:
    """Insert a group; return its new id. Raises sqlite3.IntegrityError on duplicate name."""
    cursor = conn.execute(
        "INSERT INTO groups (name, direction, color) VALUES (?, ?, ?)",
        (name, direction, color),
    )
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def delete_group(conn: sqlite3.Connection, name: str) -> bool:
    """Delete group by name (cascades to group_members). Returns True if deleted."""
    cursor = conn.execute("DELETE FROM groups WHERE name = ?", (name,))
    conn.commit()
    return cursor.rowcount == 1


def add_group_member(
    conn: sqlite3.Connection,
    group_name: str,
    reference: str,
    description: str,
) -> None:
    """Add (reference, description) to the named group.
    Raises sqlite3.IntegrityError if the key is already in any group."""
    conn.execute(
        """
        INSERT INTO group_members (group_id, reference, description)
        VALUES ((SELECT id FROM groups WHERE name = ?), ?, ?)
        """,
        (group_name, reference, description),
    )
    conn.commit()


def remove_group_member(
    conn: sqlite3.Connection,
    group_name: str,
    reference: str,
    description: str,
) -> bool:
    """Remove (reference, description) from the named group. Returns True if removed."""
    cursor = conn.execute(
        """
        DELETE FROM group_members
        WHERE group_id = (SELECT id FROM groups WHERE name = ?)
          AND reference = ? AND description = ?
        """,
        (group_name, reference, description),
    )
    conn.commit()
    return cursor.rowcount == 1


def fetch_accounts(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT account, COUNT(*) FROM transactions GROUP BY account ORDER BY account"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]
