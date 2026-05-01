import os
import sqlite3
import tempfile
from datetime import date
from typing import Any, cast

import altair as alt
import pandas as pd
import streamlit as st

from utgiftsanalys.adapters import ADAPTERS, AmbiguousAdapterError
from utgiftsanalys.chart_data import (
    GroupAmount,
    MonthActual,
    MonthPrediction,
    monthly_actuals,
    monthly_group_breakdown,
    monthly_with_predictions,
)
from utgiftsanalys.db import (
    DEFAULT_DB_PATH,
    add_group_member,
    delete_group,
    fetch_accounts,
    fetch_group_members,
    fetch_groups,
    fetch_months,
    fetch_transactions,
    get_connection,
    init_db,
    insert_group,
    remove_group_member,
    set_group_exclude,
)
from utgiftsanalys.importer import import_file
from utgiftsanalys.predictor import PredictionLine, enrich_with_actuals, next_month, predict_month
from utgiftsanalys.recurring import OneOff, RecurringPattern, build_patterns
from utgiftsanalys.stats import YearStats, compute_stats

# ── DB connection ─────────────────────────────────────────────────────────────


def _db_path() -> str:
    return os.environ.get("UTGIFTSANALYS_DB", DEFAULT_DB_PATH)


@st.cache_resource
def _get_conn() -> sqlite3.Connection:
    conn = get_connection(_db_path())
    init_db(conn)
    return conn


# ── Sidebar ───────────────────────────────────────────────────────────────────


def _sidebar(conn: sqlite3.Connection) -> str | None:
    st.sidebar.title("Utgiftsanalys")
    st.sidebar.info(f"DB: {_db_path()}")

    accounts = fetch_accounts(conn)
    options = ["All accounts"] + [a for a, _ in accounts]
    choice = st.sidebar.selectbox("Account", options)
    return None if choice == "All accounts" else choice


# ── Tab: Import ───────────────────────────────────────────────────────────────


def _tab_import(conn: sqlite3.Connection) -> None:
    st.header("Import transactions")
    uploaded = st.file_uploader("Choose a CSV file", type=["csv"])
    adapter_names = ["Auto-detect"] + [a.name for a in ADAPTERS]
    adapter_choice = st.selectbox("Adapter", adapter_names)

    if uploaded is None:
        return

    chosen_adapter = (
        None
        if adapter_choice == "Auto-detect"
        else next(a for a in ADAPTERS if a.name == adapter_choice)
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

_COLOR_COL_CONFIG = cast(
    Any,
    {"Color": st.column_config.ColorColumn("Color", width="small")},  # type: ignore[attr-defined]
)


def _pattern_df(patterns: list[RecurringPattern]) -> pd.DataFrame:
    rows = []
    for p in patterns:
        if p.amount_type == "fixed":
            amount = f"{p.fixed_amount:.2f} (fixed)"
        else:
            amount = f"{p.min_amount:.2f}–{p.max_amount:.2f} (var)"
        status = f"canceled (last: {p.end_date})" if p.status == "canceled" else "active"
        rows.append(
            {
                "Color": p.color if p.color is not None else "#ffffff",
                "Merchant": p.description,
                "Cadence": p.cadence,
                "Amount": amount,
                "Start": str(p.start_date)[:7],
                "Status": status,
            }
        )
    return pd.DataFrame(rows)


def _one_off_df(one_offs: list[OneOff]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Merchant": o.description,
                "Date": str(o.booking_date),
                "Amount": f"{abs(o.amount):.2f}",
            }
            for o in one_offs
        ]
    )


def _render_recurring_section(
    conn: sqlite3.Connection,
    patterns: list[RecurringPattern],
    direction: str,
    month: str,
    account: str | None,
) -> None:
    """Render recurring patterns: groups as expanders, individuals as a flat table."""
    group_pats = [p for p in patterns if p.color is not None]
    indiv_pats = [p for p in patterns if p.color is None]

    if group_pats:
        grp_map = {g["name"]: g for g in fetch_groups(conn, direction=direction)}
        outgoing = direction == "expenses"
        month_txs = fetch_transactions(
            conn,
            month=month,
            outgoing_only=outgoing,
            incoming_only=(not outgoing),
            account=account,
        )
        for p in group_pats:
            if p.amount_type == "fixed":
                amt_str = f"{p.fixed_amount:.2f} (fixed)"
            else:
                amt_str = f"{p.min_amount:.2f}–{p.max_amount:.2f} (var)"
            status_str = "canceled" if p.status == "canceled" else "active"
            with st.expander(f"{p.description} — {p.cadence} — {amt_str} — {status_str}"):
                grp = grp_map.get(p.description)
                if grp:
                    members = fetch_group_members(conn, grp["id"])
                    member_keys = {(m["reference"], m["description"]) for m in members}
                    member_txs = [
                        t
                        for t in month_txs
                        if (t["reference"] or "", t["description"] or "") in member_keys
                    ]
                    if member_txs:
                        df = pd.DataFrame(
                            [
                                {
                                    "Merchant": t["description"],
                                    "Date": t["booking_date"],
                                    "Amount": f"{abs(t['amount']):.2f}",
                                }
                                for t in member_txs
                            ]
                        )
                        st.dataframe(df, hide_index=True, width="stretch")
                    else:
                        st.caption("No transactions this month.")

    df = _pattern_df(indiv_pats)
    if not df.empty:
        st.dataframe(df, width="stretch", hide_index=True, column_config=_COLOR_COL_CONFIG)
    elif not group_pats:
        st.caption("(none)")


def _tab_analyze(conn: sqlite3.Connection, account: str | None) -> None:
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
    grouped = st.checkbox("Group transactions", value=True, key="analyze_grouped")

    exp_patterns, exp_one_offs = build_patterns(
        conn, account=account, direction="expenses", grouped=grouped
    )
    inc_patterns, inc_one_offs = build_patterns(
        conn, account=account, direction="income", grouped=grouped
    )
    exp_one_offs = [o for o in exp_one_offs if str(o.booking_date)[:7] == month]
    inc_one_offs = [o for o in inc_one_offs if str(o.booking_date)[:7] == month]

    if not deposits_only:
        st.subheader("Expenses — recurring")
        _render_recurring_section(conn, exp_patterns, "expenses", month, account)
        st.subheader("Expenses — one-offs")
        df = _one_off_df(exp_one_offs)
        if not df.empty:
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.caption("(none)")

    st.subheader("Income — recurring")
    _render_recurring_section(conn, inc_patterns, "income", month, account)
    st.subheader("Income — one-offs")
    df = _one_off_df(inc_one_offs)
    if not df.empty:
        st.dataframe(df, width="stretch", hide_index=True)
    else:
        st.caption("(none)")


# ── Tab: Predict ──────────────────────────────────────────────────────────────


def _actual_str(line: PredictionLine) -> str:
    if line.actual_amount is None:
        return "—"
    if line.color is None or line.members_seen == line.member_count:
        return f"{line.actual_amount:.2f}"
    return f"{line.actual_amount:.2f} ({line.members_seen}/{line.member_count} members)"


def _prediction_df(lines: list[PredictionLine], show_actuals: bool = False) -> pd.DataFrame:
    rows = []
    for line in lines:
        row: dict[str, str] = {
            "Color": line.color if line.color is not None else "#ffffff",
            "Merchant": line.description,
            "Cadence": line.cadence,
            "Predicted (SEK)": f"{line.predicted_amount:.2f}",
            "Range": line.range_str or "—",
        }
        if show_actuals:
            row["Actual (so far)"] = _actual_str(line)
        rows.append(row)
    return pd.DataFrame(rows)


def _tab_predict(conn: sqlite3.Connection, account: str | None) -> None:
    st.header("Predict")
    today = date.today()
    current_month = f"{today.year}-{today.month:02d}"
    future_months: list[str] = [current_month]
    m = next_month(today)
    for _ in range(12):
        future_months.append(m)
        y, mo = int(m[:4]), int(m[5:7])
        mo += 1
        if mo > 12:
            y += 1
            mo = 1
        m = f"{y}-{mo:02d}"
    month = st.selectbox("Month", future_months)
    grouped = st.checkbox("Group transactions", value=True, key="predict_grouped")

    exp_patterns, _ = build_patterns(conn, account=account, direction="expenses", grouped=grouped)
    inc_patterns, _ = build_patterns(conn, account=account, direction="income", grouped=grouped)
    exp_lines = predict_month(exp_patterns, month)
    inc_lines = predict_month(inc_patterns, month)

    show_actuals = month == current_month
    if show_actuals:
        enrich_with_actuals(conn, exp_lines, month, "expenses", account)
        enrich_with_actuals(conn, inc_lines, month, "income", account)

    exp_total = sum(line.predicted_amount for line in exp_lines)
    inc_total = sum(line.predicted_amount for line in inc_lines)

    col1, col2, col3 = st.columns(3)
    col1.metric("Expenses", f"{exp_total:,.2f} SEK")
    col2.metric("Income", f"{inc_total:,.2f} SEK")
    col3.metric("Net", f"{inc_total - exp_total:,.2f} SEK")

    st.subheader("Expense predictions")
    df = _prediction_df(exp_lines, show_actuals=show_actuals)
    if not df.empty:
        st.dataframe(df, width="stretch", hide_index=True, column_config=_COLOR_COL_CONFIG)
    else:
        st.caption("(none)")

    st.subheader("Income predictions")
    df = _prediction_df(inc_lines, show_actuals=show_actuals)
    if not df.empty:
        st.dataframe(df, width="stretch", hide_index=True, column_config=_COLOR_COL_CONFIG)
    else:
        st.caption("(none)")


# ── Tab: Stats ────────────────────────────────────────────────────────────────


def _stats_df(year_stats: list[YearStats], direction: str) -> pd.DataFrame:
    rows = []
    for s in year_stats:
        actual = s.actual_expense if direction == "expense" else s.actual_income
        avg = s.avg_expense if direction == "expense" else s.avg_income
        pred = (
            s.predicted_expense_remaining
            if direction == "expense"
            else s.predicted_income_remaining
        )
        if actual == 0 and pred is None:
            continue
        est_full = f"{actual + pred:.2f}" if pred is not None else f"{actual:.2f}"
        rows.append(
            {
                "Year": s.year,
                "Actual": f"{actual:.2f}",
                "Months": s.actual_months,
                "Avg/month": f"{avg:.2f}",
                "Predicted remaining": f"{pred:.2f}" if pred is not None else "—",
                "Est. full year": est_full,
            }
        )
    return pd.DataFrame(rows)


def _tab_stats(conn: sqlite3.Connection, account: str | None) -> None:
    st.header("Stats")
    year_stats = compute_stats(conn, account=account)
    if not year_stats:
        st.info("No data yet.")
        return

    st.subheader("Expenses")
    df = _stats_df(year_stats, "expense")
    if not df.empty:
        st.dataframe(df, width="stretch", hide_index=True)
    else:
        st.caption("(no data)")

    st.subheader("Income")
    df = _stats_df(year_stats, "income")
    if not df.empty:
        st.dataframe(df, width="stretch", hide_index=True)
    else:
        st.caption("(no data)")


# ── Tab: Accounts ─────────────────────────────────────────────────────────────


def _tab_accounts(conn: sqlite3.Connection) -> None:
    st.header("Accounts")
    accounts = fetch_accounts(conn)
    if not accounts:
        st.info("No accounts found.")
        return
    df = pd.DataFrame([{"Account": a, "Transactions": n} for a, n in accounts])
    st.dataframe(df, width="stretch", hide_index=True)


# ── Tab: Charts ──────────────────────────────────────────────────────────────


@st.cache_data(ttl=60)
def _cached_actuals(db_path: str, account: str | None) -> list[MonthActual]:
    conn = get_connection(db_path)
    return monthly_actuals(conn, account=account)


@st.cache_data(ttl=60)
def _cached_with_predictions(db_path: str, account: str | None) -> list[MonthPrediction]:
    conn = get_connection(db_path)
    return monthly_with_predictions(conn, account=account)


@st.cache_data(ttl=60)
def _cached_group_breakdown(db_path: str, direction: str, account: str | None) -> list[GroupAmount]:
    conn = get_connection(db_path)
    return monthly_group_breakdown(conn, direction=direction, account=account)


def _tab_charts(conn: sqlite3.Connection, account: str | None) -> None:
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

    # Chart 1 — Monthly expenses (stacked by group)
    st.subheader("Monthly expenses")
    breakdown_exp = _cached_group_breakdown(db_path, "expenses", account)
    breakdown_exp = [r for r in breakdown_exp if month_from <= r["month"] <= month_to]
    if breakdown_exp:
        df_exp = pd.DataFrame(breakdown_exp)
        groups_exp = df_exp[["group", "color"]].drop_duplicates().sort_values("group")
        domain_exp: list[str] = groups_exp["group"].tolist()
        range_exp: list[str] = groups_exp["color"].tolist()
        chart1 = (
            alt.Chart(df_exp)
            .mark_bar()
            .encode(
                x=alt.X("month:N", title="Month", sort=None),
                y=alt.Y("amount:Q", title="SEK"),
                color=alt.Color(
                    "group:N",
                    scale=alt.Scale(domain=domain_exp, range=range_exp),
                    title="Group",
                ),
                order=alt.Order("group:N"),
                tooltip=["month", "group", alt.Tooltip("amount:Q", format=".2f")],
            )
        )
    else:
        chart1 = (
            alt.Chart(df_actuals)
            .mark_bar()
            .encode(
                x=alt.X("month:N", title="Month", sort=None),
                y=alt.Y("expenses:Q", title="SEK"),
                tooltip=["month", alt.Tooltip("expenses:Q", format=".2f")],
            )
        )
    st.altair_chart(chart1, width="stretch")

    # Chart 2 — Monthly income (stacked by group)
    st.subheader("Monthly income")
    breakdown_inc = _cached_group_breakdown(db_path, "income", account)
    breakdown_inc = [r for r in breakdown_inc if month_from <= r["month"] <= month_to]
    if breakdown_inc:
        df_inc = pd.DataFrame(breakdown_inc)
        groups_inc = df_inc[["group", "color"]].drop_duplicates().sort_values("group")
        domain_inc: list[str] = groups_inc["group"].tolist()
        range_inc: list[str] = groups_inc["color"].tolist()
        chart2 = (
            alt.Chart(df_inc)
            .mark_bar()
            .encode(
                x=alt.X("month:N", title="Month", sort=None),
                y=alt.Y("amount:Q", title="SEK"),
                color=alt.Color(
                    "group:N",
                    scale=alt.Scale(domain=domain_inc, range=range_inc),
                    title="Group",
                ),
                order=alt.Order("group:N"),
                tooltip=["month", "group", alt.Tooltip("amount:Q", format=".2f")],
            )
        )
    else:
        chart2 = (
            alt.Chart(df_actuals)
            .mark_bar(color="#2ecc71")
            .encode(
                x=alt.X("month:N", title="Month", sort=None),
                y=alt.Y("income:Q", title="SEK"),
                tooltip=["month", alt.Tooltip("income:Q", format=".2f")],
            )
        )
    st.altair_chart(chart2, width="stretch")

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
    df_long["series"] = df_long["series"].map(
        {
            "actual_expenses": "Actual",
            "predicted_expenses": "Predicted",
        }
    )
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
    st.altair_chart(chart3, width="stretch")

    # Chart 4 — Prediction deviation
    st.subheader("Prediction deviation (predicted − actual)")
    deviation_color = alt.condition(
        alt.datum.deviation > 0,
        alt.value("#e74c3c"),  # red = over-predicted
        alt.value("#2ecc71"),  # green = under-predicted
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
    st.altair_chart(chart4, width="stretch")


# ── Tab: Groups ──────────────────────────────────────────────────────────────


def _tab_groups(conn: sqlite3.Connection) -> None:
    st.header("Groups")
    st.caption(
        "Combine transactions into a named group for unified recurring detection and charting."
    )

    with st.expander("➕ Create new group"):
        with st.form("create_group_form"):
            name = st.text_input("Name", placeholder="e.g. phone and internet")
            direction = st.selectbox("Direction", ["expenses", "income"])
            color = st.color_picker("Color", value="#3498db")
            submitted = st.form_submit_button("Create")
        if submitted:
            if not name.strip():
                st.error("Name is required.")
            else:
                try:
                    insert_group(conn, name.strip(), direction, color)
                    st.cache_data.clear()
                    st.success(f"Group '{name.strip()}' created.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error(f"A group named '{name.strip()}' already exists.")

    all_groups = fetch_groups(conn)
    if not all_groups:
        st.info("No groups yet. Create one above.")
        return

    for grp in all_groups:
        with st.expander(f"{grp['name']}  ·  {grp['direction']}  ·  {grp['color']}"):
            col1, col2 = st.columns([5, 1])
            col1.markdown(f"**{grp['name']}** — {grp['direction']}")
            if col2.button("Delete", key=f"del_grp_{grp['id']}", type="secondary"):
                delete_group(conn, grp["name"])
                st.cache_data.clear()
                st.rerun()

            excluded = bool(grp["exclude_from_prediction"])
            new_excluded = st.toggle(
                "Exclude from predictions",
                value=excluded,
                key=f"excl_{grp['id']}",
            )
            if new_excluded != excluded:
                set_group_exclude(conn, grp["name"], new_excluded)
                st.rerun()

            members = fetch_group_members(conn, grp["id"])
            if members:
                st.markdown("**Members:**")
                for m in members:
                    mc1, mc2 = st.columns([5, 1])
                    label = (
                        m["description"]
                        if m["reference"] == m["description"]
                        else f"{m['reference']} / {m['description']}"
                    )
                    mc1.text(label)
                    if mc2.button("Remove", key=f"rem_{grp['id']}_{m['id']}"):
                        remove_group_member(conn, grp["name"], m["reference"], m["description"])
                        st.cache_data.clear()
                        st.rerun()
            else:
                st.caption("No members yet.")

            # Add members
            outgoing = grp["direction"] == "expenses"
            all_txs = fetch_transactions(conn, outgoing_only=outgoing, incoming_only=(not outgoing))
            existing_keys = {(m["reference"], m["description"]) for m in members}
            known_pairs = sorted(
                {(t["reference"] or "", t["description"] or "") for t in all_txs},
                key=lambda k: k[1].lower(),
            )
            available = [
                (ref, desc) for ref, desc in known_pairs if (ref, desc) not in existing_keys
            ]
            if available:
                labels = [desc if ref == desc else f"{ref} / {desc}" for ref, desc in available]
                with st.form(key=f"add_members_form_{grp['id']}"):
                    selected = st.multiselect("Add members", labels)
                    if st.form_submit_button("Add selected"):
                        label_to_pair = dict(zip(labels, available, strict=True))
                        added = 0
                        for lbl in selected:
                            ref, desc = label_to_pair[lbl]
                            try:
                                add_group_member(conn, grp["name"], ref, desc)
                                added += 1
                            except sqlite3.IntegrityError:
                                st.warning(f"'{desc}' is already in another group.")
                        if added:
                            st.cache_data.clear()
                            st.rerun()
            else:
                st.caption("All available transactions are already assigned to a group.")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    st.set_page_config(page_title="Utgiftsanalys", page_icon="💰", layout="wide")
    conn = _get_conn()
    account = _sidebar(conn)

    tab_import, tab_analyze, tab_predict, tab_stats, tab_accounts, tab_charts, tab_groups = st.tabs(
        ["Import", "Analyze", "Predict", "Stats", "Accounts", "Charts", "Groups"]
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
    with tab_groups:
        _tab_groups(conn)


main()
