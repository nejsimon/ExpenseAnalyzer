from dataclasses import dataclass, field


@dataclass
class CsvAdapter:
    name: str
    required_columns: list[str]
    column_map: dict[str, str]
    delimiter: str = ","
    decimal_sep: str = "."


class AmbiguousAdapterError(Exception):
    def __init__(self, candidates: list[CsvAdapter]) -> None:
        self.candidates = candidates
        super().__init__(f"Ambiguous adapter: {[a.name for a in candidates]}")


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

ADAPTERS: list[CsvAdapter] = [SwedBankAdapter]


def detect_adapter(
    headers: list[str],
    adapters: list[CsvAdapter] | None = None,
) -> "CsvAdapter | list[CsvAdapter]":
    """Return one CsvAdapter, a list if ambiguous, or raise ValueError if none match."""
    if adapters is None:
        adapters = ADAPTERS
    cleaned = [h.strip().lstrip("﻿") for h in headers]
    matches = [a for a in adapters if all(col in cleaned for col in a.required_columns)]
    if not matches:
        tried = [a.name for a in adapters]
        raise ValueError(
            f"No adapter matched the CSV headers.\n"
            f"Headers found: {cleaned}\n"
            f"Adapters tried: {tried}"
        )
    if len(matches) == 1:
        return matches[0]
    return matches
