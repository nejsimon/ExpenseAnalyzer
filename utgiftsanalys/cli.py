from typing import TypedDict, cast

import click

from .adapters import ADAPTERS, AmbiguousAdapterError
from .calendar_utils import current_analysis_month
from .db import (
    DEFAULT_DB_PATH,
    add_group_member,
    delete_group,
    fetch_accounts,
    fetch_groups,
    get_connection,
    init_db,
    insert_group,
    remove_group_member,
    set_group_exclude,
)
from .importer import import_file
from .output import (
    render_accounts,
    render_adapters,
    render_groups,
    render_import_result,
    render_prediction,
    render_recurring_summary,
    render_stats,
)
from .predictor import enrich_with_actuals, predict_month
from .recurring import build_patterns
from .stats import compute_stats


class ContextObject(TypedDict):
    db: str
    account: str | None


@click.group()
@click.option("--db", default=DEFAULT_DB_PATH, show_default=True, help="Path to SQLite database.")
@click.option("--account", default=None, help="Filter by account number (Kontonummer).")
@click.pass_context
def main(ctx: click.Context, db: str, account: str | None) -> None:
    """Utgiftsanalys — Swedish bank transaction analyser."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    ctx.obj["account"] = account


@main.command("import")
@click.argument("file", type=click.Path(exists=True))
@click.option("--output", "fmt", default="table", type=click.Choice(["table", "csv"]))
@click.option(
    "--adapter", "adapter_name", default=None, help="Adapter name (skips auto-detection)."
)
@click.pass_context
def import_cmd(ctx: click.Context, file: str, fmt: str, adapter_name: str | None) -> None:
    """Import transactions from a CSV file."""
    adapter = None
    if adapter_name is not None:
        adapter = next((a for a in ADAPTERS if a.name == adapter_name), None)
        if adapter is None:
            known = ", ".join(a.name for a in ADAPTERS)
            click.echo(f"Unknown adapter '{adapter_name}'. Available: {known}", err=True)
            return
    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    try:
        inserted, skipped, _ = import_file(file, conn, adapter=adapter)
    except AmbiguousAdapterError as exc:
        click.echo("Multiple adapters matched this file:")
        for i, a in enumerate(exc.candidates, 1):
            click.echo(f"  {i}. {a.name}")
        choice = click.prompt("Select adapter number", type=int)
        chosen = exc.candidates[choice - 1]
        inserted, skipped, _ = import_file(file, conn, adapter=chosen)
    conn.close()
    render_import_result(inserted, skipped, fmt)


@main.command("adapters")
@click.option("--output", "fmt", default="table", type=click.Choice(["table", "csv"]))
def adapters_cmd(fmt: str) -> None:
    """List available CSV adapters."""
    render_adapters(ADAPTERS, fmt)


@main.command()
@click.option("--month", default=None, help="Analysis month YYYY-MM (default: current month).")
@click.option("--output", "fmt", default="table", type=click.Choice(["table", "csv"]))
@click.option(
    "--deposits-only", is_flag=True, default=False, help="Show only the income/deposits section."
)
@click.option(
    "--flat", is_flag=True, default=False, help="Show individual merchants instead of groups."
)
@click.pass_context
def analyze(
    ctx: click.Context, month: str | None, fmt: str, deposits_only: bool, flat: bool
) -> None:
    """Show recurring patterns and one-offs."""
    if month is None:
        month = current_analysis_month()
    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    account = ctx_obj["account"]
    exp_patterns, exp_one_offs = build_patterns(
        conn, account=account, direction="expenses", grouped=not flat
    )
    inc_patterns, inc_one_offs = build_patterns(
        conn, account=account, direction="income", grouped=not flat
    )
    conn.close()
    exp_one_offs = [o for o in exp_one_offs if str(o.booking_date)[:7] == month]
    inc_one_offs = [o for o in inc_one_offs if str(o.booking_date)[:7] == month]
    render_recurring_summary(
        exp_patterns, exp_one_offs, inc_patterns, inc_one_offs, fmt, deposits_only
    )


@main.command()
@click.option("--month", default=None, help="Target month YYYY-MM (default: current month).")
@click.option("--output", "fmt", default="table", type=click.Choice(["table", "csv"]))
@click.option(
    "--flat", is_flag=True, default=False, help="Show individual merchants instead of groups."
)
@click.pass_context
def predict(ctx: click.Context, month: str | None, fmt: str, flat: bool) -> None:
    """Predict expenses and income for a given month."""
    current_month = current_analysis_month()
    if month is None:
        month = current_month
    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    account = ctx_obj["account"]
    exp_patterns, _ = build_patterns(conn, account=account, direction="expenses", grouped=not flat)
    inc_patterns, _ = build_patterns(conn, account=account, direction="income", grouped=not flat)
    exp_lines = predict_month(exp_patterns, month)
    inc_lines = predict_month(inc_patterns, month)
    show_actuals = month == current_month
    if show_actuals:
        enrich_with_actuals(conn, exp_lines, month, "expenses", account)
        enrich_with_actuals(conn, inc_lines, month, "income", account)
    conn.close()
    render_prediction(exp_lines, inc_lines, month, fmt, show_actuals=show_actuals)


@main.command()
@click.option("--output", "fmt", default="table", type=click.Choice(["table", "csv"]))
@click.pass_context
def stats(ctx: click.Context, fmt: str) -> None:
    """Show yearly expense and income statistics."""
    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    year_stats = compute_stats(conn, account=ctx_obj["account"])
    conn.close()
    render_stats(year_stats, fmt)


@main.command()
@click.option("--output", "fmt", default="table", type=click.Choice(["table", "csv"]))
@click.pass_context
def accounts(ctx: click.Context, fmt: str) -> None:
    """List all known accounts and their transaction counts."""
    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    accts = fetch_accounts(conn)
    conn.close()
    render_accounts(accts, fmt)


@main.group("groups")
def groups_cmd() -> None:
    """Manage transaction groups."""


@groups_cmd.command("list")
@click.option("--direction", default=None, type=click.Choice(["expenses", "income"]))
@click.option("--output", "fmt", default="table", type=click.Choice(["table", "csv"]))
@click.pass_context
def groups_list(ctx: click.Context, direction: str | None, fmt: str) -> None:
    """List all groups."""
    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    grps = fetch_groups(conn, direction=direction)
    conn.close()
    render_groups(grps, fmt)


@groups_cmd.command("add")
@click.argument("name")
@click.option("--direction", required=True, type=click.Choice(["expenses", "income"]))
@click.option("--color", default="#888888", show_default=True, help="Hex color for charts.")
@click.pass_context
def groups_add(ctx: click.Context, name: str, direction: str, color: str) -> None:
    """Create a group."""
    import sqlite3 as _sqlite3

    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    try:
        insert_group(conn, name, direction, color)
        click.echo(f"Group '{name}' created.")
    except _sqlite3.IntegrityError:
        click.echo(f"Error: a group named '{name}' already exists.", err=True)
    finally:
        conn.close()


@groups_cmd.command("remove")
@click.argument("name")
@click.option("--confirm", is_flag=True, help="Required to confirm deletion.")
@click.pass_context
def groups_remove(ctx: click.Context, name: str, confirm: bool) -> None:
    """Delete a group (and its members)."""
    if not confirm:
        click.echo("Pass --confirm to delete the group.")
        return
    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    removed = delete_group(conn, name)
    conn.close()
    if removed:
        click.echo(f"Group '{name}' removed.")
    else:
        click.echo(f"No group named '{name}'.", err=True)


@groups_cmd.command("add-member")
@click.argument("name")
@click.option("--reference", required=True, help="Transaction reference.")
@click.option("--description", required=True, help="Transaction description.")
@click.pass_context
def groups_add_member(ctx: click.Context, name: str, reference: str, description: str) -> None:
    """Add a (reference, description) key to a group."""
    import sqlite3 as _sqlite3

    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    try:
        add_group_member(conn, name, reference, description)
        click.echo("Member added.")
    except _sqlite3.IntegrityError:
        click.echo(
            f"Error: '{description}' is already assigned to a group, or group '{name}' not found.",
            err=True,
        )
    finally:
        conn.close()


@groups_cmd.command("remove-member")
@click.argument("name")
@click.option("--reference", required=True, help="Transaction reference.")
@click.option("--description", required=True, help="Transaction description.")
@click.pass_context
def groups_remove_member(ctx: click.Context, name: str, reference: str, description: str) -> None:
    """Remove a (reference, description) key from a group."""
    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    removed = remove_group_member(conn, name, reference, description)
    conn.close()
    if removed:
        click.echo("Member removed.")
    else:
        click.echo("Member not found in that group.", err=True)


@groups_cmd.command("set-predict-exclude")
@click.argument("name")
@click.option("--exclude/--no-exclude", default=True, help="Exclude this group from predictions.")
@click.pass_context
def groups_set_predict_exclude(ctx: click.Context, name: str, exclude: bool) -> None:
    """Exclude or include a group in predictions."""
    ctx_obj = cast(ContextObject, ctx.obj)
    conn = get_connection(ctx_obj["db"])
    init_db(conn)
    found = set_group_exclude(conn, name, exclude)
    conn.close()
    if found:
        status = "excluded from" if exclude else "included in"
        click.echo(f"Group '{name}' is now {status} predictions.")
    else:
        click.echo(f"No group named '{name}'.", err=True)


@main.command()
@click.option("--confirm", is_flag=True, help="Required to confirm deletion.")
@click.pass_context
def reset(ctx: click.Context, confirm: bool) -> None:
    """Drop and recreate the database."""
    if not confirm:
        click.echo("Pass --confirm to reset the database.")
        return
    import os

    ctx_obj = cast(ContextObject, ctx.obj)
    db_path = ctx_obj["db"]
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = get_connection(db_path)
    init_db(conn)
    conn.close()
    click.echo(f"Database reset: {db_path}")
