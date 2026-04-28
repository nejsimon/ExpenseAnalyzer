# 02 — CSV Import

**Status:** [x] done

## Description

Parse Swedish bank CSV files, auto-detect encoding, normalize columns to internal names, compute dedup hash, and persist to SQLite.

## Acceptance Criteria

- `utgiftsanalys import sample.csv` inserts N rows and prints "Inserted N, skipped 0".
- Re-importing the same file prints "Inserted 0, skipped N" (idempotent).
- Files encoded in Windows-1252 are imported correctly (Swedish characters preserved).
- Files encoded in UTF-8 are imported correctly.
- `Radnummer` is stored as `row_number` but is NOT used as a unique identifier.

## CSV Column Mapping

| CSV column (Swedish)  | Internal name      |
|-----------------------|--------------------|
| Radnummer             | row_number         |
| Clearingnummer        | clearing           |
| Kontonummer           | account            |
| Produkt               | product            |
| Valuta                | currency           |
| Bokföringsdag         | booking_date       |
| Transaktionsdag       | transaction_date   |
| Valutadag             | value_date         |
| Referens              | reference          |
| Beskrivning           | description        |
| Belopp                | amount             |
| Bokfört saldo         | balance            |

## Implementation Notes

- `detect_encoding(path)`: run `chardet.detect()` on first 64 KB; if confidence < 0.7 or result is None, try `windows-1252` then `utf-8`.
- Dedup hash: `SHA-256(booking_date + "|" + reference + "|" + description + "|" + amount)` stored as hex in `import_hash`.
- `INSERT OR IGNORE INTO transactions` handles duplicates silently.
- `analysis_month` is computed at import time via `calendar_utils.get_analysis_month`.
