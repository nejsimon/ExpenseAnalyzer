import sqlite3
from pathlib import Path

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
"""


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)
    conn.commit()


def insert_transaction(conn: sqlite3.Connection, tx: dict) -> bool:
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
    clauses = []
    params: list = []
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
    clauses = []
    params: list = []
    if account:
        clauses.append("account = ?")
        params.append(account)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT DISTINCT analysis_month FROM transactions {where} ORDER BY analysis_month",
        params,
    ).fetchall()
    return [r[0] for r in rows]


def fetch_accounts(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT account, COUNT(*) FROM transactions GROUP BY account ORDER BY account"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]
