import sqlite3
from typing import TypedDict

from .db import fetch_group_members, fetch_groups, fetch_months, fetch_transactions
from .predictor import predict_month
from .recurring import build_patterns

_OTHER_COLOR = "#888888"


class MonthActual(TypedDict):
    month: str
    expenses: float
    income: float


class MonthPrediction(TypedDict):
    month: str
    actual_expenses: float
    predicted_expenses: float
    deviation: float


class GroupAmount(TypedDict):
    month: str
    group: str
    color: str
    amount: float


def monthly_actuals(conn: sqlite3.Connection, account: str | None = None) -> list[MonthActual]:
    """Return per-month expense and income totals for all months in the DB."""
    rows: list[MonthActual] = []
    for month in fetch_months(conn, account=account):
        txs = fetch_transactions(conn, month=month, outgoing_only=False, account=account)
        expenses = sum(abs(t["amount"]) for t in txs if t["amount"] < 0)
        income = sum(t["amount"] for t in txs if t["amount"] > 0)
        rows.append({"month": month, "expenses": expenses, "income": income})
    return rows


def monthly_group_breakdown(
    conn: sqlite3.Connection,
    direction: str = "expenses",
    account: str | None = None,
) -> list[GroupAmount]:
    """Return per-month amounts split by group and an 'Other' catch-all."""
    member_to_group: dict[tuple[str, str], tuple[str, str]] = {}
    for grp in fetch_groups(conn, direction=direction):
        for m in fetch_group_members(conn, grp["id"]):
            member_to_group[(m["reference"], m["description"])] = (grp["name"], grp["color"])

    result: list[GroupAmount] = []
    for month in fetch_months(conn, account=account):
        txs = fetch_transactions(
            conn,
            month=month,
            outgoing_only=(direction == "expenses"),
            incoming_only=(direction == "income"),
            account=account,
        )
        totals: dict[tuple[str, str], float] = {}
        for tx in txs:
            key = (tx["reference"] or "", tx["description"] or "")
            group_name, color = member_to_group.get(key, ("Other", _OTHER_COLOR))
            totals[(group_name, color)] = totals.get((group_name, color), 0.0) + abs(tx["amount"])
        for (group, color), amount in totals.items():
            result.append({"month": month, "group": group, "color": color, "amount": amount})
    return result


def monthly_with_predictions(
    conn: sqlite3.Connection, account: str | None = None
) -> list[MonthPrediction]:
    """Return per-month actuals alongside approximate predictions.

    Predictions use all-time patterns (not hold-out), so they are approximate
    for historical months — useful for showing prediction quality trends.
    """
    exp_patterns, _ = build_patterns(conn, account=account, direction="expenses")
    rows: list[MonthPrediction] = []
    for rec in monthly_actuals(conn, account=account):
        month = rec["month"]
        predicted = sum(line.predicted_amount for line in predict_month(exp_patterns, month))
        rows.append(
            {
                "month": month,
                "actual_expenses": rec["expenses"],
                "predicted_expenses": predicted,
                "deviation": predicted - rec["expenses"],
            }
        )
    return rows
