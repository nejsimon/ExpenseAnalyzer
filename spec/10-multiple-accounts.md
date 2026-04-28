# 10 — Multiple Accounts

**Status:** [x] done

## Description

Support importing from multiple bank accounts into the same database, with per-account filtering on all commands.

## Acceptance Criteria

- Transactions from different accounts (Kontonummer) are kept separate in the DB.
- `utgiftsanalys import account1.csv` and `import account2.csv` both work; both are stored.
- `--account 123456789` filters all commands (analyze, predict, stats) to that account.
- `utgiftsanalys accounts` lists all known account numbers and transaction counts.
- Without `--account`, all commands aggregate across all accounts.
- Deduplication still works correctly: same transaction re-imported for the same account is skipped; a transaction with identical fields but a different account number is treated as distinct.

## Implementation Notes

- `account` column already exists in the `transactions` table (stores Kontonummer from CSV). No schema change needed.
- Add `account: str | None = None` parameter to `fetch_transactions`, `build_patterns`, `compute_stats`, and `predict_month`.
- Add global `--account` option to the Click group (alongside `--db`), passed via `ctx.obj`.
- `import_hash` already includes account-neutral fields. Since two different accounts could have the same transaction (unlikely but possible), consider whether account should be part of the hash. Decision: **include account number in the import_hash** to avoid cross-account collisions.
  - Hash key: `f"{booking_date}|{reference}|{description}|{amount}|{account_number}"`
- New command `accounts`:
  ```
  utgiftsanalys accounts
  Account       Transactions
  ─────────────────────────
  123456789     248
  987654321     132
  ```
- `fetch_accounts(conn) -> list[tuple[str, int]]` in `db.py`.

## Migration Note

Existing databases built before this spec had `import_hash` computed without the account number. When this feature is implemented, run `utgiftsanalys reset --confirm` and re-import.
