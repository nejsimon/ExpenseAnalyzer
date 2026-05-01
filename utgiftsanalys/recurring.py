import sqlite3
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Literal

from .db import fetch_group_members, fetch_groups, fetch_transactions

AmountClassification = tuple[Literal["fixed"], float] | tuple[Literal["variable"], float, float]

_PERIOD_DAYS = {"monthly": 30, "quarterly": 91, "yearly": 365}


@dataclass
class RecurringPattern:
    reference: str
    description: str
    cadence: str
    amount_type: str
    fixed_amount: float | None
    min_amount: float | None
    max_amount: float | None
    start_date: date
    end_date: date | None
    status: str
    amounts: list[float]
    color: str | None = None
    exclude_from_prediction: bool = False


@dataclass
class OneOff:
    reference: str
    description: str
    booking_date: date
    amount: float


def _detect_cadence(analysis_months: list[str]) -> str | None:
    """Detect cadence from a list of YYYY-MM analysis_month strings.

    Deduplicates by month, computes integer month gaps, then classifies by
    checking whether >50% of gaps fall within one month of the expected period.
    """

    def _to_int(ym: str) -> int:
        return int(ym[:4]) * 12 + int(ym[5:7])

    unique = sorted(set(_to_int(m) for m in analysis_months))
    if len(unique) < 2:
        return None

    gaps = [unique[i + 1] - unique[i] for i in range(len(unique) - 1)]

    for cadence, expected, tolerance in [
        ("monthly", 1, 0),
        ("quarterly", 3, 1),
        ("yearly", 12, 2),
    ]:
        matching = sum(1 for g in gaps if abs(g - expected) <= tolerance)
        if matching / len(gaps) > 0.5:
            return cadence
    return None


def _classify_amounts(amounts: list[float]) -> AmountClassification:
    """Returns ('fixed', amount) or ('variable', min, max)."""
    abs_amounts = [abs(a) for a in amounts]
    mean = statistics.mean(abs_amounts)
    stdev = statistics.stdev(abs_amounts) if len(abs_amounts) > 1 else 0.0

    # Check if last 3+ occurrences form a new fixed price (price increase)
    if len(abs_amounts) >= 3:
        recent = abs_amounts[-3:]
        recent_stdev = statistics.stdev(recent) if len(recent) > 1 else 0.0
        if recent_stdev < 5.0 or (mean > 0 and recent_stdev / mean < 0.02):
            return ("fixed", statistics.mean(recent))

    if stdev < 5.0 or (mean > 0 and stdev / mean < 0.02):
        return ("fixed", mean)
    return ("variable", min(abs_amounts), max(abs_amounts))


def build_patterns(
    conn: sqlite3.Connection,
    reference_date: date | None = None,
    account: str | None = None,
    direction: str = "expenses",
    grouped: bool = True,
) -> tuple[list[RecurringPattern], list[OneOff]]:
    today = reference_date or date.today()
    rows = fetch_transactions(
        conn,
        outgoing_only=(direction == "expenses"),
        incoming_only=(direction == "income"),
        account=account,
    )

    # Index all rows by (reference, description) for efficient group lookup
    key_to_rows: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        key = (row["reference"] or "", row["description"] or "")
        key_to_rows.setdefault(key, []).append(row)

    patterns: list[RecurringPattern] = []
    one_offs: list[OneOff] = []
    excluded_keys: set[tuple[str, str]] = set()

    # ── Group phase: process named groups before individual keys ──────────────
    if grouped:
        for grp in fetch_groups(conn, direction=direction):
            members = fetch_group_members(conn, grp["id"])
            member_keys = {(m["reference"], m["description"]) for m in members}
            excluded_keys |= member_keys

            month_amounts: dict[str, list[float]] = {}
            all_group_txs: list[sqlite3.Row] = []
            for mk in member_keys:
                for tx in key_to_rows.get(mk, []):
                    month_amounts.setdefault(tx["analysis_month"], []).append(tx["amount"])
                    all_group_txs.append(tx)

            if not all_group_txs:
                continue

            synthetic_months = sorted(month_amounts)
            synthetic_amounts = [sum(month_amounts[m]) for m in synthetic_months]

            cadence = _detect_cadence(synthetic_months)
            if cadence is None:
                for tx in all_group_txs:
                    one_offs.append(
                        OneOff(
                            reference=grp["name"],
                            description=grp["name"],
                            booking_date=date.fromisoformat(tx["booking_date"]),
                            amount=tx["amount"],
                        )
                    )
                continue

            classification = _classify_amounts(synthetic_amounts)
            if classification[0] == "fixed":
                amount_type, fixed_amount = "fixed", classification[1]
                min_amount = max_amount = None
            else:
                amount_type, fixed_amount = "variable", None
                _, min_amount, max_amount = classification

            all_dates = sorted(date.fromisoformat(t["booking_date"]) for t in all_group_txs)
            last_seen = max(all_dates)
            period = _PERIOD_DAYS[cadence]
            status = "canceled" if (today - last_seen).days > 1.5 * period else "active"
            end_date = last_seen if status == "canceled" else None

            patterns.append(
                RecurringPattern(
                    reference=grp["name"],
                    description=grp["name"],
                    cadence=cadence,
                    amount_type=amount_type,
                    fixed_amount=fixed_amount,
                    min_amount=min_amount,
                    max_amount=max_amount,
                    start_date=min(all_dates),
                    end_date=end_date,
                    status=status,
                    amounts=synthetic_amounts,
                    color=grp["color"],
                    exclude_from_prediction=bool(grp["exclude_from_prediction"]),
                )
            )

    # ── Per-key phase: individual transaction keys not claimed by any group ───
    key_groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        key = (row["reference"] or "", row["description"] or "")
        if key not in excluded_keys:
            key_groups.setdefault(key, []).append(row)

    for (ref, desc), txs in key_groups.items():
        txs_sorted = sorted(txs, key=lambda t: t["booking_date"])
        dates = [date.fromisoformat(t["booking_date"]) for t in txs_sorted]
        amounts = [t["amount"] for t in txs_sorted]

        cadence = _detect_cadence([t["analysis_month"] for t in txs_sorted])
        if cadence is None:
            for tx in txs:
                one_offs.append(
                    OneOff(
                        reference=ref,
                        description=desc,
                        booking_date=date.fromisoformat(tx["booking_date"]),
                        amount=tx["amount"],
                    )
                )
            continue

        classification = _classify_amounts(amounts)
        if classification[0] == "fixed":
            amount_type, fixed_amount = "fixed", classification[1]
            min_amount = max_amount = None
        else:
            amount_type = "variable"
            fixed_amount = None
            _, min_amount, max_amount = classification

        last_seen = max(dates)
        period = _PERIOD_DAYS[cadence]
        if (today - last_seen).days > 1.5 * period:
            status = "canceled"
            end_date = last_seen
        else:
            status = "active"
            end_date = None

        patterns.append(
            RecurringPattern(
                reference=ref,
                description=desc,
                cadence=cadence,
                amount_type=amount_type,
                fixed_amount=fixed_amount,
                min_amount=min_amount,
                max_amount=max_amount,
                start_date=min(dates),
                end_date=end_date,
                status=status,
                amounts=amounts,
            )
        )

    patterns.sort(key=lambda p: (p.cadence, p.description))
    one_offs.sort(key=lambda o: o.booking_date)
    return patterns, one_offs
