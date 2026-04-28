# 12 — CSV Adapters

**Status:** [x] done

## Description

Replace the hardcoded Swedbank column map with an adapter system. Each adapter describes a CSV schema. The correct adapter is detected automatically from the header row. This allows future banks to be added without changing core import logic.

## Acceptance Criteria

- Importing a Swedbank CSV works exactly as before (no regression).
- The adapter is selected automatically based on the CSV headers; no flag required.
- If headers match more than one adapter, the user is prompted to choose (CLI) or an error is returned (API).
- Importing a CSV with unrecognized headers prints a clear error listing the headers found and the adapters tried.
- Adding a new adapter requires only adding a new `CsvAdapter` instance — no changes to `import_file`.
- `utgiftsanalys adapters` lists available adapters by name.

## Adapter Interface

```python
@dataclass
class CsvAdapter:
    name: str                      # e.g. "swedbank"
    required_columns: list[str]    # subset that must all be present to match
    column_map: dict[str, str]     # CSV column name → internal field name
    delimiter: str = ","
    decimal_sep: str = "."         # character used for decimal in amounts
```

Detection: for each registered adapter, check whether all `required_columns` are present in the CSV header row.

- **No match** → raise `ValueError` with a helpful message listing the headers found and adapters tried.
- **Exactly one match** → use it.
- **Multiple matches** → CLI: prompt the user to pick with `click.prompt` offering a numbered list. API (`app.py`): return HTTP 422 with `{"detail": "Ambiguous adapter", "candidates": ["swedbank", "..."]}`.

Alternatively, the `import` command accepts `--adapter NAME` to skip detection entirely.

## Swedbank Adapter

```python
SwedBankAdapter = CsvAdapter(
    name="swedbank",
    required_columns=["Bokföringsdag", "Beskrivning", "Belopp", "Kontonummer"],
    column_map={
        "Radnummer":       "row_number",
        "Clearingnummer":  "clearing",
        "Kontonummer":     "account",
        "Produkt":         "product",
        "Valuta":          "currency",
        "Bokföringsdag":   "booking_date",
        "Transaktionsdag": "transaction_date",
        "Valutadag":       "value_date",
        "Referens":        "reference",
        "Beskrivning":     "description",
        "Belopp":          "amount",
        "Bokfört saldo":   "balance",
    },
    delimiter=",",
    decimal_sep=".",
)
```

## Implementation Notes

- New file `adapters.py` containing the `CsvAdapter` dataclass and a `ADAPTERS: list[CsvAdapter]` registry.
- `detect_adapter(headers: list[str]) -> CsvAdapter | list[CsvAdapter]` — returns one adapter, a list if ambiguous, or raises `ValueError` if none match.
- `importer.py`: replace `_COLUMN_MAP` constant with a call to `detect_adapter`; pass `adapter.delimiter` to `csv.DictReader`.
- `_parse_amount` should use `adapter.decimal_sep` (Swedish banks sometimes use comma as decimal separator).
- `import_file` gains an optional `adapter: CsvAdapter | None = None` parameter; if provided, skips detection.
- CLI `import` command gains `--adapter NAME` option.
- `adapters` CLI command: `utgiftsanalys adapters` → table of adapter names and their required columns.
- Headers for detection are read after encoding detection; strip BOM / whitespace from each header before comparing.
