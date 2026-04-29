from dataclasses import dataclass
from datetime import date

from .recurring import RecurringPattern


@dataclass
class PredictionLine:
    description: str
    cadence: str
    predicted_amount: float
    amount_type: str
    range_str: str


def _hits_month(pattern: RecurringPattern, target_year: int, target_month: int) -> bool:
    start = pattern.start_date
    start_index = start.year * 12 + start.month
    target_index = target_year * 12 + target_month
    if target_index < start_index:
        return False
    if pattern.cadence == "monthly":
        return True
    if pattern.cadence == "quarterly":
        return (target_index - start_index) % 3 == 0
    if pattern.cadence == "yearly":
        return target_month == start.month
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
            )
        )

    lines.sort(key=lambda ln: (ln.cadence, ln.description))
    return lines


def next_month(d: date) -> str:
    if d.month == 12:
        return f"{d.year + 1}-01"
    return f"{d.year}-{d.month + 1:02d}"
