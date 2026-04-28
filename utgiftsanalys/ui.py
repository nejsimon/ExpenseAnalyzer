import os
import tempfile
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from utgiftsanalys.adapters import ADAPTERS, AmbiguousAdapterError
from utgiftsanalys.chart_data import monthly_actuals, monthly_with_predictions
from utgiftsanalys.db import DEFAULT_DB_PATH, fetch_accounts, fetch_months, get_connection, init_db
from utgiftsanalys.importer import import_file
from utgiftsanalys.predictor import next_month, predict_month
from utgiftsanalys.recurring import build_patterns
from utgiftsanalys.stats import compute_stats


# ── DB connection ─────────────────────────────────────────────────────────────

def _db_path() -> str:
    return os.environ.get("UTGIFTSANALYS_DB", DEFAULT_DB_PATH)


@st.cache_resource
def _get_conn():
    conn = get_connection(_db_path())
    init_db(conn)
    return conn


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _sidebar(conn) -> str | None:
    st.sidebar.title("Utgiftsanalys")
    st.sidebar.info(f"DB: {_db_path()}")

    accounts = fetch_accounts(conn)
    options = ["All accounts"] + [a for a, _ in accounts]
    choice = st.sidebar.selectbox("Account", options)
    return None if choice == "All accounts" else choice


# ── Tab: Import ───────────────────────────────────────────────────────────────

def _tab_import(conn) -> None:
    st.header("Import transactions")
    uploaded = st.file_uploader("Choose a CSV file", type=["csv"])
    adapter_names = ["Auto-detect"] + [a.name for a in ADAPTERS]
    adapter_choice = st.selectbox("Adapter", adapter_names)

    if uploaded is None:
        return

    chosen_adapter = None if adapter_choice == "Auto-detect" else next(
        a for a in ADAPTERS if a.name == adapter_choice
    )

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    try:
        inserted, skipped, warnings = import_file(tmp_path, conn, adapter=chosen_adapter)
        st.success(f"Inserted {inserted}, skipped {skipped}.")
        for w in warnings:
            st.warning(w)
        # Invalidate cached data after a successful import
        st.cache_data.clear()
    except AmbiguousAdapterError as exc:
        candidates = [a.name for a in exc.candidates]
        resolved = st.selectbox("Multiple adapters matched — choose one:", candidates)
        if st.button("Import with selected adapter"):
            adapter = next(a for a in exc.candidates if a.name == resolved)
            inserted, skipped, warnings = import_file(tmp_path, conn, adapter=adapter)
            st.success(f"Inserted {inserted}, skipped {skipped}.")
            for w in warnings:
                st.warning(w)
            st.cache_data.clear()
    except ValueError as exc:
        st.error(str(exc))
    finally:
        os.unlink(tmp_path)


# ── Tab: Analyze ──────────────────────────────────────────────────────────────

def _pattern_df(patterns) -> pd.DataFrame:
    rows = []
    for p in patterns:
        if p.amount_type == "fixed":
            amount = f"{p.fixed_amount:.2f} (fixed)"
        else:
            amount = f"{p.min_amount:.2f}–{p.max_amount:.2f} (var)"
        status = f"canceled (last: {p.end_date})" if p.status == "canceled" else "active"
        rows.append({
            "Merchant": p.description,
            "Cadence": p.cadence,
            "Amount": amount,
            "Start": str(p.start_date)[:7],
            "Status": status,
        })
    return pd.DataFrame(rows)


def _one_off_df(one_offs) -> pd.DataFrame:
    return pd.DataFrame([
        {"Merchant": o.description, "Date": str(o.booking_date), "Amount": f"{abs(o.amount):.2f}"}
        for o in one_offs
    ])


def _tab_analyze(conn, account: str | None) -> None:
    st.header("Analyze")
    months = fetch_months(conn, account=account)
    if not months:
        st.info("No data yet. Import a CSV file first.")
        return

    today = date.today()
    current = f"{today.year}-{today.month:02d}"
    default_idx = months.index(current) if current in months else len(months) - 1
    month = st.selectbox("Month", months, index=default_idx)
    deposits_only = st.checkbox("Deposits only")

    exp_patterns, exp_one_offs = build_patterns(conn, account=account, direction="expenses")
    inc_patterns, inc_one_offs = build_patterns(conn, account=account, direction="income")
    exp_one_offs = [o for o in exp_one_offs if str(o.booking_date)[:7] == month]
    inc_one_offs = [o for o in inc_one_offs if str(o.booking_date)[:7] == month]

    if not deposits_only:
        st.subheader("Expenses — recurring")
        df = _pattern_df(exp_patterns)
        st.dataframe(df, width="stretch", hide_index=True) if not df.empty else st.caption("(none)")
        st.subheader("Expenses — one-offs")
        df = _one_off_df(exp_one_offs)
        st.dataframe(df, width="stretch", hide_index=True) if not df.empty else st.caption("(none)")

    st.subheader("Income — recurring")
    df = _pattern_df(inc_patterns)
    st.dataframe(df, width="stretch", hide_index=True) if not df.empty else st.caption("(none)")
    st.subheader("Income — one-offs")
    df = _one_off_df(inc_one_offs)
    st.dataframe(df, width="stretch", hide_index=True) if not df.empty else st.caption("(none)")


# ── Tab: Predict ──────────────────────────────────────────────────────────────

def _prediction_df(lines) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Merchant": l.description,
            "Cadence": l.cadence,
            "Predicted (SEK)": f"{l.predicted_amount:.2f}",
            "Range": l.range_str or "—",
        }
        for l in lines
    ])


def _tab_predict(conn, account: str | None) -> None:
    st.header("Predict")
    today = date.today()
    default_month = next_month(today)
    # Offer the next 12 months
    future_months = []
    m = default_month
    for _ in range(12):
        future_months.append(m)
        y, mo = int(m[:4]), int(m[5:7])
        mo += 1
        if mo > 12:
            y += 1
            mo = 1
        m = f"{y}-{mo:02d}"
    month = st.selectbox("Month", future_months)

    exp_patterns, _ = build_patterns(conn, account=account, direction="expenses")
    inc_patterns, _ = build_patterns(conn, account=account, direction="income")
    exp_lines = predict_month(exp_patterns, month)
    inc_lines = predict_month(inc_patterns, month)
    exp_total = sum(l.predicted_amount for l in exp_lines)
    inc_total = sum(l.predicted_amount for l in inc_lines)

    col1, col2, col3 = st.columns(3)
    col1.metric("Expenses", f"{exp_total:,.2f} SEK")
    col2.metric("Income", f"{inc_total:,.2f} SEK")
    col3.metric("Net", f"{inc_total - exp_total:,.2f} SEK")

    st.subheader("Expense predictions")
    df = _prediction_df(exp_lines)
    st.dataframe(df, width="stretch", hide_index=True) if not df.empty else st.caption("(none)")

    st.subheader("Income predictions")
    df = _prediction_df(inc_lines)
    st.dataframe(df, width="stretch", hide_index=True) if not df.empty else st.caption("(none)")


# ── Tab: Stats ────────────────────────────────────────────────────────────────

def _stats_df(year_stats, direction: str) -> pd.DataFrame:
    rows = []
    for s in year_stats:
        actual = s.actual_expense if direction == "expense" else s.actual_income
        avg = s.avg_expense if direction == "expense" else s.avg_income
        pred = s.predicted_expense_remaining if direction == "expense" else s.predicted_income_remaining
        if actual == 0 and pred is None:
            continue
        est_full = f"{actual + pred:.2f}" if pred is not None else f"{actual:.2f}"
        rows.append({
            "Year": s.year,
            "Actual": f"{actual:.2f}",
            "Months": s.actual_months,
            "Avg/month": f"{avg:.2f}",
            "Predicted remaining": f"{pred:.2f}" if pred is not None else "—",
            "Est. full year": est_full,
        })
    return pd.DataFrame(rows)


def _tab_stats(conn, account: str | None) -> None:
    st.header("Stats")
    year_stats = compute_stats(conn, account=account)
    if not year_stats:
        st.info("No data yet.")
        return

    st.subheader("Expenses")
    df = _stats_df(year_stats, "expense")
    st.dataframe(df, width="stretch", hide_index=True) if not df.empty else st.caption("(no data)")

    st.subheader("Income")
    df = _stats_df(year_stats, "income")
    st.dataframe(df, width="stretch", hide_index=True) if not df.empty else st.caption("(no data)")


# ── Tab: Accounts ─────────────────────────────────────────────────────────────

def _tab_accounts(conn) -> None:
    st.header("Accounts")
    accounts = fetch_accounts(conn)
    if not accounts:
        st.info("No accounts found.")
        return
    df = pd.DataFrame([{"Account": a, "Transactions": n} for a, n in accounts])
    st.dataframe(df, width="stretch", hide_index=True)


# ── Tab: Charts ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def _cached_actuals(db_path: str, account: str | None) -> list[dict]:
    conn = get_connection(db_path)
    return monthly_actuals(conn, account=account)


@st.cache_data(ttl=60)
def _cached_with_predictions(db_path: str, account: str | None) -> list[dict]:
    conn = get_connection(db_path)
    return monthly_with_predictions(conn, account=account)


def _tab_charts(conn, account: str | None) -> None:
    st.header("Charts")
    months = fetch_months(conn, account=account)
    if not months:
        st.info("No data yet. Import a CSV file first.")
        return

    # Date range filter (month granularity via string bounds)
    col_from, col_to = st.columns(2)
    month_from = col_from.selectbox("From", months, index=0, key="chart_from")
    month_to = col_to.selectbox("To", months, index=len(months) - 1, key="chart_to")
    if month_from > month_to:
        st.warning("'From' month is after 'To' month.")
        return

    db_path = _db_path()
    actuals = _cached_actuals(db_path, account)
    pred_data = _cached_with_predictions(db_path, account)

    # Apply date range filter
    actuals = [r for r in actuals if month_from <= r["month"] <= month_to]
    pred_data = [r for r in pred_data if month_from <= r["month"] <= month_to]

    if not actuals:
        st.info("No data in the selected range.")
        return

    df_actuals = pd.DataFrame(actuals)
    df_pred = pd.DataFrame(pred_data)

    # Chart 1 — Monthly expenses
    st.subheader("Monthly expenses")
    chart1 = (
        alt.Chart(df_actuals)
        .mark_bar()
        .encode(
            x=alt.X("month:N", title="Month", sort=None),
            y=alt.Y("expenses:Q", title="SEK"),
            tooltip=["month", alt.Tooltip("expenses:Q", format=".2f")],
        )
    )
    st.altair_chart(chart1, use_container_width=True)

    # Chart 2 — Monthly income
    st.subheader("Monthly income")
    chart2 = (
        alt.Chart(df_actuals)
        .mark_bar(color="#2ecc71")
        .encode(
            x=alt.X("month:N", title="Month", sort=None),
            y=alt.Y("income:Q", title="SEK"),
            tooltip=["month", alt.Tooltip("income:Q", format=".2f")],
        )
    )
    st.altair_chart(chart2, use_container_width=True)

    if df_pred.empty or df_pred["predicted_expenses"].sum() == 0:
        st.caption("No recurring patterns found — skipping prediction charts.")
        return

    # Chart 3 — Predicted vs actual expenses
    st.subheader("Predicted vs actual expenses")
    st.caption("Predictions use all-time patterns applied retroactively (approximate).")
    df_long = df_pred.melt(
        id_vars="month",
        value_vars=["actual_expenses", "predicted_expenses"],
        var_name="series",
        value_name="SEK",
    )
    df_long["series"] = df_long["series"].map({
        "actual_expenses": "Actual",
        "predicted_expenses": "Predicted",
    })
    chart3 = (
        alt.Chart(df_long)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:N", title="Month", sort=None),
            y=alt.Y("SEK:Q", title="SEK"),
            color=alt.Color("series:N", title="Series"),
            tooltip=["month", "series", alt.Tooltip("SEK:Q", format=".2f")],
        )
    )
    st.altair_chart(chart3, use_container_width=True)

    # Chart 4 — Prediction deviation
    st.subheader("Prediction deviation (predicted − actual)")
    deviation_color = alt.condition(
        alt.datum.deviation > 0,
        alt.value("#e74c3c"),   # red = over-predicted
        alt.value("#2ecc71"),   # green = under-predicted
    )
    chart4 = (
        alt.Chart(df_pred)
        .mark_bar()
        .encode(
            x=alt.X("month:N", title="Month", sort=None),
            y=alt.Y("deviation:Q", title="SEK (predicted − actual)"),
            color=deviation_color,
            tooltip=["month", alt.Tooltip("deviation:Q", format=".2f")],
        )
    )
    st.altair_chart(chart4, use_container_width=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="Utgiftsanalys", page_icon="💰", layout="wide")
    conn = _get_conn()
    account = _sidebar(conn)

    tab_import, tab_analyze, tab_predict, tab_stats, tab_accounts, tab_charts = st.tabs(
        ["Import", "Analyze", "Predict", "Stats", "Accounts", "Charts"]
    )
    with tab_import:
        _tab_import(conn)
    with tab_analyze:
        _tab_analyze(conn, account)
    with tab_predict:
        _tab_predict(conn, account)
    with tab_stats:
        _tab_stats(conn, account)
    with tab_accounts:
        _tab_accounts(conn)
    with tab_charts:
        _tab_charts(conn, account)


main()
