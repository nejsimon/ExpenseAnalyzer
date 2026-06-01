import os
import sqlite3
import tempfile

import altair as alt
import pandas as pd
import streamlit as st
from pandas.io.formats.style import Styler

from expense_analyzer.adapters import ADAPTERS, AmbiguousAdapterError
from expense_analyzer.calendar_utils import current_analysis_month
from expense_analyzer.chart_data import (
    GroupAmount,
    MonthActual,
    MonthPrediction,
    monthly_actuals,
    monthly_group_breakdown,
    monthly_with_predictions,
)
from expense_analyzer.db import (
    DEFAULT_DB_PATH,
    add_group_member,
    delete_group,
    fetch_accounts,
    fetch_all_group_member_keys,
    fetch_group_members,
    fetch_groups,
    fetch_months,
    fetch_transactions,
    get_connection,
    init_db,
    insert_group,
    remove_group_member,
    set_group_exclude,
    update_group_color,
    update_group_icon,
)
from expense_analyzer.importer import import_file
from expense_analyzer.predictor import PredictionLine, enrich_with_actuals, predict_month
from expense_analyzer.recurring import OneOff, RecurringPattern, build_patterns
from expense_analyzer.stats import YearStats, compute_stats

# ── DB connection ─────────────────────────────────────────────────────────────


def _db_path() -> str:
    return os.environ.get("EXPENSE_ANALYZER_DB", DEFAULT_DB_PATH)


@st.cache_resource
def _get_conn() -> sqlite3.Connection:
    conn = get_connection(_db_path())
    init_db(conn)
    return conn


# ── Sidebar ───────────────────────────────────────────────────────────────────


def _sidebar(conn: sqlite3.Connection) -> str | None:
    st.sidebar.title("Expense Analyzer")
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


# ── Icon palette ─────────────────────────────────────────────────────────────

_ICON_PALETTE: list[str] = [
    # Home
    "🏠",
    "💡",
    "🔥",
    "🌊",
    "🛠️",
    "🔑",
    # Transport
    "🚗",
    "🚌",
    "🚲",
    "✈️",
    "🚂",
    "⛽",
    # Food
    "🛒",
    "🍽️",
    "☕",
    "🍕",
    "🥤",
    "🥦",
    # Health
    "💊",
    "🏥",
    "💪",
    "🧘",
    "🦷",
    "👁️",
    # Entertainment
    "📺",
    "🎮",
    "🎵",
    "🎬",
    "📚",
    "🎭",
    # Tech / comms
    "📱",
    "💻",
    "📶",
    "🖥️",
    # Finance
    "💰",
    "🏦",
    "💳",
    "📈",
    "🏧",
    # Personal care
    "👕",
    "💇",
    "🐕",
    "🐈",
    "🧴",
    # Education / work
    "🎓",
    "📐",
    "💼",
    "👔",
    "📊",
    # Misc
    "🎁",
    "🧾",
    "🌍",
]


def _group_label(name: str, icon: str | None) -> str:
    return f"{icon} {name}" if icon else name


# ── Tab: Analyze ──────────────────────────────────────────────────────────────


def _contrast_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#000000" if luminance > 0.179 else "#ffffff"


def _style_by_color(df: pd.DataFrame, color_map: dict[str, str]) -> Styler:
    def _row(row: pd.Series) -> list[str]:
        color = color_map.get(str(row["Merchant"]))
        if color is None:
            return [""] * len(row)
        text = _contrast_color(color)
        s = f"background-color: {color}; color: {text}"
        return [s] * len(row)

    return df.style.apply(_row, axis=1)


def _pattern_df(
    patterns: list[RecurringPattern], icon_map: dict[str, str | None] | None = None
) -> pd.DataFrame:
    rows = []
    for p in patterns:
        if p.amount_type == "fixed":
            amount = f"{p.fixed_amount:.2f} (fixed)"
        else:
            amount = f"{p.min_amount:.2f}–{p.max_amount:.2f} (var)"
        status = f"canceled (last: {p.end_date})" if p.status == "canceled" else "active"
        icon = icon_map.get(p.description) if icon_map else None
        rows.append(
            {
                "Merchant": _group_label(p.description, icon),
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
    patterns: list[RecurringPattern],
    icon_map: dict[str, str | None] | None = None,
) -> None:
    """Render all recurring patterns in a single table with group rows colored."""
    df = _pattern_df(patterns, icon_map=icon_map)
    if df.empty:
        st.caption("(none)")
        return
    # color_map keys must match the (possibly icon-prefixed) Merchant column values
    color_map = {
        _group_label(p.description, icon_map.get(p.description) if icon_map else None): p.color
        for p in patterns
        if p.color is not None
    }
    st.dataframe(_style_by_color(df, color_map), width="stretch", hide_index=True)


def _tab_analyze(conn: sqlite3.Connection, account: str | None) -> None:
    st.header("Analyze")
    months = fetch_months(conn, account=account)
    if not months:
        st.info("No data yet. Import a CSV file first.")
        return

    current = current_analysis_month()
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

    icon_map: dict[str, str | None] = {
        grp["name"]: grp["icon"] for grp in fetch_groups(conn) if grp["icon"]
    }

    if not deposits_only:
        st.subheader("Expenses — recurring")
        _render_recurring_section(exp_patterns, icon_map=icon_map)
        st.subheader("Expenses — one-offs")
        df = _one_off_df(exp_one_offs)
        if not df.empty:
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.caption("(none)")

    st.subheader("Income — recurring")
    _render_recurring_section(inc_patterns, icon_map=icon_map)
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


def _prediction_df(
    lines: list[PredictionLine],
    show_actuals: bool = False,
    actual_label: str = "Actual",
    icon_map: dict[str, str | None] | None = None,
) -> pd.DataFrame:
    rows = []
    for line in lines:
        icon = icon_map.get(line.description) if icon_map else None
        row: dict[str, str] = {
            "Merchant": _group_label(line.description, icon),
            "Cadence": line.cadence,
            "Predicted (SEK)": f"{line.predicted_amount:.2f}",
            "Range": line.range_str or "—",
        }
        if show_actuals:
            row[actual_label] = _actual_str(line)
        rows.append(row)
    return pd.DataFrame(rows)


def _tab_predict(conn: sqlite3.Connection, account: str | None) -> None:
    st.header("Predict")
    current_month = current_analysis_month()

    past_months = sorted(m for m in fetch_months(conn, account=account) if m < current_month)
    # Start future months from the month after current_month (not after date.today(),
    # which can skip a month when today is still in the pre-first-bank-day window).
    future_months: list[str] = []
    cy, cmo = int(current_month[:4]), int(current_month[5:7])
    cmo += 1
    if cmo > 12:
        cy, cmo = cy + 1, 1
    m = f"{cy}-{cmo:02d}"
    for _ in range(12):
        future_months.append(m)
        y, mo = int(m[:4]), int(m[5:7])
        mo += 1
        if mo > 12:
            y += 1
            mo = 1
        m = f"{y}-{mo:02d}"
    all_months = past_months + [current_month] + future_months
    default_idx = len(past_months)  # current month
    month = st.selectbox("Month", all_months, index=default_idx)
    grouped = st.checkbox("Group transactions", value=True, key="predict_grouped")

    exp_patterns, _ = build_patterns(conn, account=account, direction="expenses", grouped=grouped)
    inc_patterns, _ = build_patterns(conn, account=account, direction="income", grouped=grouped)
    exp_lines = predict_month(exp_patterns, month)
    inc_lines = predict_month(inc_patterns, month)

    icon_map = {grp["name"]: grp["icon"] for grp in fetch_groups(conn) if grp["icon"]}

    show_actuals = month <= current_month
    actual_label = "Actual (so far)" if month == current_month else "Actual"
    if show_actuals:
        enrich_with_actuals(conn, exp_lines, month, "expenses", account)
        enrich_with_actuals(conn, inc_lines, month, "income", account)

    exp_total = sum(line.predicted_amount for line in exp_lines)
    inc_total = sum(line.predicted_amount for line in inc_lines)

    col1, col2, col3 = st.columns(3)
    col1.metric("Expenses", f"{exp_total:,.2f} SEK")
    col2.metric("Income", f"{inc_total:,.2f} SEK")
    col3.metric("Net", f"{inc_total - exp_total:,.2f} SEK")

    if show_actuals:
        exp_actual = sum(ln.actual_amount for ln in exp_lines if ln.actual_amount is not None)
        inc_actual = sum(ln.actual_amount for ln in inc_lines if ln.actual_amount is not None)
        acol1, acol2, acol3 = st.columns(3)
        acol1.metric(f"{actual_label} expenses", f"{exp_actual:,.2f} SEK")
        acol2.metric(f"{actual_label} income", f"{inc_actual:,.2f} SEK")
        acol3.metric(f"{actual_label} net", f"{inc_actual - exp_actual:,.2f} SEK")

    st.subheader("Expense predictions")
    df = _prediction_df(
        exp_lines, show_actuals=show_actuals, actual_label=actual_label, icon_map=icon_map
    )
    if not df.empty:
        exp_colors = {
            _group_label(ln.description, icon_map.get(ln.description)): ln.color
            for ln in exp_lines
            if ln.color is not None
        }
        st.dataframe(_style_by_color(df, exp_colors), width="stretch", hide_index=True)
    else:
        st.caption("(none)")

    st.subheader("Income predictions")
    df = _prediction_df(
        inc_lines, show_actuals=show_actuals, actual_label=actual_label, icon_map=icon_map
    )
    if not df.empty:
        inc_colors = {
            _group_label(ln.description, icon_map.get(ln.description)): ln.color
            for ln in inc_lines
            if ln.color is not None
        }
        st.dataframe(_style_by_color(df, inc_colors), width="stretch", hide_index=True)
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

    # Build icon label map for chart legends: group name → "icon name" or just "name"
    label_map = {grp["name"]: _group_label(grp["name"], grp["icon"]) for grp in fetch_groups(conn)}

    # Chart 1 — Monthly expenses (stacked by group)
    st.subheader("Monthly expenses")
    breakdown_exp = _cached_group_breakdown(db_path, "expenses", account)
    breakdown_exp = [r for r in breakdown_exp if month_from <= r["month"] <= month_to]
    if breakdown_exp:
        df_exp = pd.DataFrame(breakdown_exp)
        df_exp["group"] = df_exp["group"].map(lambda g: label_map.get(g, g))
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
        df_inc["group"] = df_inc["group"].map(lambda g: label_map.get(g, g))
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

    current_month = current_analysis_month()
    # Months before the current analysis month have complete actual data.
    # The current month is in progress: actual is partial so deviation is misleading.
    df_pred_complete = df_pred[df_pred["month"] < current_month]
    df_pred_current = df_pred[df_pred["month"] == current_month]

    # Chart 3 — Predicted vs actual expenses
    st.subheader("Predicted vs actual expenses")
    caption3 = "Predictions use all-time patterns applied retroactively (approximate)."
    if not df_pred_current.empty:
        caption3 += " Current month shows predicted only (in progress)."
    st.caption(caption3)

    # Historical rows contribute both Actual and Predicted; current month Predicted only.
    df_long = df_pred_complete.melt(
        id_vars="month",
        value_vars=["actual_expenses", "predicted_expenses"],
        var_name="series",
        value_name="SEK",
    )
    df_long["series"] = df_long["series"].map(
        {"actual_expenses": "Actual", "predicted_expenses": "Predicted"}
    )
    if not df_pred_current.empty:
        row = df_pred_current.iloc[0]
        df_long = pd.concat(
            [
                df_long,
                pd.DataFrame(
                    [
                        {
                            "month": row["month"],
                            "series": "Predicted",
                            "SEK": row["predicted_expenses"],
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    # Linear trend over historical actual expenses (pure Python, no new deps)
    months_hist = df_pred_complete["month"].tolist()
    y_vals = df_pred_complete["actual_expenses"].tolist()
    n_hist = len(months_hist)
    if n_hist >= 2:
        x_mean = (n_hist - 1) / 2
        y_mean = sum(y_vals) / n_hist
        ss_xy = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(y_vals))
        ss_xx = sum((i - x_mean) ** 2 for i in range(n_hist))
        if ss_xx > 0:
            slope = ss_xy / ss_xx
            intercept = y_mean - slope * x_mean
            trend_rows: list[dict[str, object]] = [
                {"month": m, "series": "Trend", "SEK": intercept + slope * i}
                for i, m in enumerate(months_hist)
            ]
            if not df_pred_current.empty:
                trend_rows.append(
                    {
                        "month": current_month,
                        "series": "Trend",
                        "SEK": intercept + slope * n_hist,
                    }
                )
            df_long = pd.concat([df_long, pd.DataFrame(trend_rows)], ignore_index=True)

    chart3 = (
        alt.Chart(df_long)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:N", title="Month", sort=None),
            y=alt.Y("SEK:Q", title="SEK"),
            color=alt.Color("series:N", title="Series"),
            strokeDash=alt.StrokeDash(
                "series:N",
                scale=alt.Scale(
                    domain=["Actual", "Predicted", "Trend"],
                    range=[[1, 0], [4, 2], [6, 3]],
                ),
            ),
            tooltip=["month", "series", alt.Tooltip("SEK:Q", format=".2f")],
        )
    )
    st.altair_chart(chart3, width="stretch")

    # Chart 4 — Prediction deviation (complete months only)
    st.subheader("Prediction deviation (predicted − actual)")
    if df_pred_complete.empty:
        st.caption("No complete months in range.")
    else:
        if not df_pred_current.empty:
            st.caption("Current month excluded (in progress).")
        deviation_color = alt.condition(
            alt.datum.deviation > 0,
            alt.value("#e74c3c"),  # red = over-predicted
            alt.value("#2ecc71"),  # green = under-predicted
        )
        chart4 = (
            alt.Chart(df_pred_complete)
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

    all_assigned_keys = fetch_all_group_member_keys(conn)

    for grp in all_groups:
        current_icon: str | None = grp["icon"]
        expander_title = (
            f"{current_icon} {grp['name']}  ·  {grp['direction']}"
            if current_icon
            else f"{grp['name']}  ·  {grp['direction']}"
        )
        with st.expander(expander_title):
            col1, col2 = st.columns([5, 1])
            col1.markdown(f"**{grp['name']}** — {grp['direction']}")
            if col2.button("Delete", key=f"del_grp_{grp['id']}", type="secondary"):
                delete_group(conn, grp["name"])
                st.cache_data.clear()
                st.rerun()

            new_color = st.color_picker("Color", value=grp["color"], key=f"color_{grp['id']}")
            if new_color != grp["color"]:
                update_group_color(conn, grp["name"], new_color)
                st.cache_data.clear()
                st.rerun()

            # Icon picker — compact emoji grid
            st.caption(f"Icon: {current_icon or '(none)'}")
            icon_cols = st.columns(10)
            for idx, emoji in enumerate(_ICON_PALETTE):
                if icon_cols[idx % 10].button(
                    emoji,
                    key=f"icon_{grp['id']}_{idx}",
                    type="primary" if emoji == current_icon else "secondary",
                ):
                    update_group_icon(conn, grp["name"], emoji)
                    st.cache_data.clear()
                    st.rerun()
            if current_icon and st.button("✕ Clear icon", key=f"icon_clear_{grp['id']}"):
                update_group_icon(conn, grp["name"], None)
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
                    if m["is_offset"]:
                        label = f"{label} (offset)"
                    mc1.text(label)
                    if mc2.button("Remove", key=f"rem_{grp['id']}_{m['id']}"):
                        remove_group_member(conn, grp["name"], m["reference"], m["description"])
                        st.cache_data.clear()
                        st.rerun()
            else:
                st.caption("No members yet.")

            # Add members — income groups may also accept expense transactions as
            # offsets (e.g. a back-transfer that reduces the deposit total).
            all_txs = fetch_transactions(conn, outgoing_only=False, incoming_only=False)
            # Build a map from key → typical direction so we can label offsets
            key_is_expense: dict[tuple[str, str], bool] = {}
            for t in all_txs:
                key = (t["reference"] or "", t["description"] or "")
                if key not in key_is_expense:
                    key_is_expense[key] = t["amount"] < 0

            # For expense groups show only expense transactions; income groups show all
            if grp["direction"] == "expenses":
                candidate_keys = {k for k, is_exp in key_is_expense.items() if is_exp}
            else:
                candidate_keys = set(key_is_expense)

            known_pairs = sorted(
                candidate_keys,
                key=lambda k: k[1].lower(),
            )
            available = [
                (ref, desc) for ref, desc in known_pairs if (ref, desc) not in all_assigned_keys
            ]
            if available:
                labels = []
                for ref, desc in available:
                    base = desc if ref == desc else f"{ref} / {desc}"
                    if grp["direction"] == "income" and key_is_expense.get((ref, desc)):
                        base = f"{base} (offset)"
                    labels.append(base)
                with st.form(key=f"add_members_form_{grp['id']}"):
                    selected = st.multiselect("Add members", labels)
                    if st.form_submit_button("Add selected"):
                        label_to_pair = dict(zip(labels, available, strict=True))
                        added = 0
                        for lbl in selected:
                            ref, desc = label_to_pair[lbl]
                            is_offset = grp["direction"] == "income" and key_is_expense.get(
                                (ref, desc), False
                            )
                            try:
                                add_group_member(conn, grp["name"], ref, desc, is_offset=is_offset)
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
    st.set_page_config(page_title="Expense Analyzer", page_icon="💰", layout="wide")
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
