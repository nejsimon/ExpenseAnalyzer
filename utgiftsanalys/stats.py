import sqlite3
from dataclasses import dataclass
from datetime import date

from .db import fetch_transactions, fetch_months
from .predictor import predict_month
from .recurring import build_patterns


@dataclass
class YearStats:
    year: int
    actual_expense: float
    actual_income: float
    actual_months: int
    avg_expense: float
    avg_income: float
    predicted_expense_remaining: float | None   # None for past years
    predicted_income_remaining: float | None    # None until spec 11


def compute_stats(conn: sqlite3.Connection, account: str | None = None) -> list[YearStats]:
    all_months_in_db = set(fetch_months(conn, account=account))
    if not all_months_in_db:
        return []

    all_txs = fetch_transactions(conn, outgoing_only=False, account=account)
    current_year = date.today().year

    # Group transactions by year
    by_year: dict[int, list[sqlite3.Row]] = {}
    for tx in all_txs:
        year = int(tx["analysis_month"][:4])
        by_year.setdefault(year, []).append(tx)

    # Build patterns once for each direction — used for current-year prediction
    exp_patterns, _ = build_patterns(conn, account=account, direction="expenses")
    inc_patterns, _ = build_patterns(conn, account=account, direction="income")

    result: list[YearStats] = []
    for year in sorted(by_year):
        txs = by_year[year]
        actual_expense = sum(abs(t["amount"]) for t in txs if t["amount"] < 0)
        actual_income = sum(t["amount"] for t in txs if t["amount"] > 0)
        actual_months = len({t["analysis_month"] for t in txs})
        avg_expense = actual_expense / actual_months if actual_months else 0.0
        avg_income = actual_income / actual_months if actual_months else 0.0

        predicted_expense = None
        predicted_income = None

        if year == current_year:
            remaining = [
                f"{year}-{m:02d}" for m in range(1, 13)
                if f"{year}-{m:02d}" not in all_months_in_db
            ]
            predicted_expense = sum(
                sum(line.predicted_amount for line in predict_month(exp_patterns, ym))
                for ym in remaining
            )
            predicted_income = sum(
                sum(line.predicted_amount for line in predict_month(inc_patterns, ym))
                for ym in remaining
            ) or None

        result.append(YearStats(
            year=year,
            actual_expense=actual_expense,
            actual_income=actual_income,
            actual_months=actual_months,
            avg_expense=avg_expense,
            avg_income=avg_income,
            predicted_expense_remaining=predicted_expense,
            predicted_income_remaining=predicted_income,
        ))

    return result
