import sqlite3
from dataclasses import dataclass
from datetime import date

from .db import fetch_group_members, fetch_transactions
from .recurring import RecurringPattern


@dataclass
class PredictionLine:
    description: str
    cadence: str
    predicted_amount: float
    amount_type: str
    range_str: str
    reference: str = ""
    color: str | None = None
    actual_amount: float | None = None
    member_count: int | None = None
    members_seen: int | None = None


def _hits_month(pattern: RecurringPattern, target_year: int, target_month: int) -> bool:
    start = pattern.start_date
    start_index = start.year * 12 + start.month
    target_index = target_year * 12 + target_month
    if target_index < start_index:
        return False
    if pattern.cadence == "monthly":
        return True
    # Use last_analysis_month as phase anchor when available — prevents drift when
    # start_date falls in a different cycle than recent occurrences.
    if pattern.last_analysis_month:
        anchor_year = int(pattern.last_analysis_month[:4])
        anchor_month = int(pattern.last_analysis_month[5:7])
        anchor_index = anchor_year * 12 + anchor_month
    else:
        anchor_index = start_index
    if pattern.cadence == "quarterly":
        return (target_index - anchor_index) % 3 == 0
    if pattern.cadence == "yearly":
        hit_month = anchor_month if pattern.last_analysis_month else start.month
        return target_month == hit_month
    return False


def _weighted_average(amounts: list[float]) -> float:
    abs_amounts = [abs(a) for a in amounts]
    n = len(abs_amounts)
    total_weight = n * (n + 1) / 2
    return sum((i + 1) * a for i, a in enumerate(abs_amounts)) / total_weight


def predict_month(
    patterns: list[RecurringPattern],
    target_month: str,
) -> list[PredictionLine]:
    year, month = int(target_month[:4]), int(target_month[5:7])
    lines: list[PredictionLine] = []

    for p in patterns:
        if p.status != "active":
            continue
        if p.exclude_from_prediction:
            continue
        if not _hits_month(p, year, month):
            continue

        if p.amount_type == "fixed":
            predicted = p.fixed_amount or 0.0
            range_str = ""
        else:
            predicted = _weighted_average(p.amounts)
            range_str = f"{p.min_amount:.2f}–{p.max_amount:.2f}"

        lines.append(
            PredictionLine(
                description=p.description,
                cadence=p.cadence,
                predicted_amount=predicted,
                amount_type=p.amount_type,
                range_str=range_str,
                reference=p.reference,
                color=p.color,
            )
        )

    lines.sort(key=lambda ln: (ln.cadence, ln.description))
    return lines


def next_month(d: date) -> str:
    if d.month == 12:
        return f"{d.year + 1}-01"
    return f"{d.year}-{d.month + 1:02d}"


def enrich_with_actuals(
    conn: sqlite3.Connection,
    lines: list[PredictionLine],
    month: str,
    direction: str = "expenses",
    account: str | None = None,
) -> None:
    txs = fetch_transactions(
        conn,
        month=month,
        outgoing_only=(direction == "expenses"),
        incoming_only=(direction == "income"),
        account=account,
    )
    tx_index: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for tx in txs:
        key = (tx["reference"] or "", tx["description"] or "")
        tx_index.setdefault(key, []).append(tx)

    for line in lines:
        if line.color is None:
            matching = tx_index.get((line.reference, line.description), [])
            if matching:
                line.actual_amount = sum(abs(tx["amount"]) for tx in matching)
        else:
            grp_row = conn.execute(
                "SELECT id FROM groups WHERE name = ?", (line.description,)
            ).fetchone()
            if grp_row is None:
                continue
            members = fetch_group_members(conn, grp_row["id"])
            seen = 0
            total = 0.0
            for m in members:
                key = (m["reference"], m["description"])
                member_txs = tx_index.get(key, [])
                if member_txs:
                    seen += 1
                    total += sum(abs(tx["amount"]) for tx in member_txs)
            line.member_count = len(members)
            line.members_seen = seen
            if seen > 0:
                line.actual_amount = total
