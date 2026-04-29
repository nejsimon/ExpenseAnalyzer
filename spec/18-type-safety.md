# 18 — Type Safety

**Status:** [ ] pending

## Description

Introduce mypy in strict mode across all source files, define a `TransactionDict` TypedDict to replace the untyped `dict` in the DB layer, and wire mypy into a pre-commit hook so type errors block commits.

## Acceptance Criteria

- `uv run mypy utgiftsanalys/` exits 0 with no errors or warnings.
- `strict = true` is set in `[tool.mypy]` in `pyproject.toml`.
- Every function in all source files (`cli.py`, `db.py`, `importer.py`, `recurring.py`, `predictor.py`, `output.py`, `chart_data.py`, `adapters.py`, `calendar_utils.py`, `stats.py`, `ui.py`) has fully annotated parameters and return types.
- `TransactionDict` TypedDict is defined in `db.py` and used as the parameter type for `insert_transaction`.
- `# type: ignore` comments exist only where a third-party library provides no stubs and no workaround is possible; each carries an inline explanation.
- `Any` is absent except in the same unavoidable cases.
- `.pre-commit-config.yaml` exists at the repo root with a local mypy hook.
- `git commit` fails if mypy reports errors.

## Tool Choice

**mypy** with `--strict` is chosen because:
- Most mature Python type checker (10+ years); `typeshed` and the `types-*` PyPI stub ecosystem give broad third-party coverage.
- `dmypy` daemon provides fast incremental checks during development (`uv run dmypy run -- utgiftsanalys/`).
- Strict mode is comprehensive: enables `--disallow-any-generics`, `--disallow-untyped-calls`, `--warn-return-any`, and a dozen more checks.

## pyproject.toml Changes

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "mypy>=1.10",
    "types-tabulate",
    "pre-commit>=3.7",
]

[tool.mypy]
strict = true
python_version = "3.11"
exclude = ["tests/"]
```

`types-tabulate` covers `output.py`'s `tabulate` import. `streamlit` and `altair` ship inline type annotations; no extra stubs are needed. `holidays` and `chardet` do not ship stubs; add `[[tool.mypy.overrides]]` entries with `ignore_missing_imports = true` for those two packages rather than using `# type: ignore` at each call site.

## TransactionDict TypedDict (db.py)

```python
from typing import TypedDict

class TransactionDict(TypedDict):
    row_number:       int | None
    clearing:         str | None
    account:          str | None
    product:          str | None
    currency:         str | None
    booking_date:     str
    transaction_date: str | None
    value_date:       str | None
    reference:        str | None
    description:      str | None
    amount:           float
    balance:          float | None
    import_hash:      str
    analysis_month:   str
```

Update `insert_transaction(conn, tx: TransactionDict) -> bool`. `fetch_transactions` continues to return `list[sqlite3.Row]` (typed in typeshed as a mapping; dict-style `row["key"]` access is accepted by mypy).

## Per-file Annotation Work

**db.py** — Add `TransactionDict`; annotate all CRUD functions including new group CRUD from spec 17. `fetch_months` returns `list[str]`; `fetch_accounts` returns `list[tuple[str, int]]`.

**recurring.py** — `_detect_cadence(analysis_months: list[str]) -> str | None`. `_classify_amounts` returns a union type; use an explicit `tuple` union or define a small helper type alias:
```python
AmountClassification = tuple[Literal["fixed"], float] | tuple[Literal["variable"], float, float]
```
Rename the internal `groups` dict in `build_patterns` to `key_groups` (avoids shadowing the `fetch_groups` import from spec 17 and the module-level `groups` names).

**cli.py** — Click types `ctx.obj` as `Any`. Define a `ContextObject` TypedDict and use `cast`:
```python
class ContextObject(TypedDict):
    db: str
    account: str | None
```
Use `ctx_obj = cast(ContextObject, ctx.obj)` in each subcommand. The `ctx.ensure_object(dict)` line needs `# type: ignore[arg-type]` (Click's type signature is too broad).

**chart_data.py** — Define TypedDicts for return types:
```python
class MonthActual(TypedDict):
    month: str; expenses: float; income: float

class MonthPrediction(TypedDict):
    month: str; actual_expenses: float; predicted_expenses: float; deviation: float
```
Return `list[MonthActual]` and `list[MonthPrediction]` respectively.

**output.py** — Convert `_fmt_amount` and `_fmt_status` lambda/local helpers to module-level annotated functions. All `render_*` functions return `None`.

**predictor.py** — `predict_month` returns `list[PredictionLine]`; `_hits_month` returns `bool`; all helpers annotated.

**importer.py** — `detect_encoding(path: str) -> str`; `import_file` returns `tuple[int, int, list[str]]`; `_normalize_row(raw: dict[str, str], adapter: CsvAdapter) -> TransactionDict`.

**adapters.py**, **calendar_utils.py**, **stats.py** — Annotate all function parameters and return types (mostly already present; verify under `--strict`).

**ui.py** — All tab functions accept `sqlite3.Connection` and return `None`. The `@st.cache_resource` decorated `_get_conn` function: mypy may flag the decorator; add `# type: ignore[misc]` if needed (Streamlit's decorator typing is imperfect). `pd.DataFrame` return types are fine without `pandas-stubs`; if strict mode flags DataFrame usage, add an overrides section for `pandas` with `ignore_missing_imports = true`.

## Pre-commit Configuration

Create `.pre-commit-config.yaml` at the repo root:

```yaml
repos:
  - repo: local
    hooks:
      - id: mypy
        name: mypy type check
        language: system
        entry: uv run mypy utgiftsanalys/
        types: [python]
        pass_filenames: false
```

After creating the file, install the hook:

```
uv run pre-commit install
```

This places a script in `.git/hooks/pre-commit` that runs mypy before every commit. A non-zero exit aborts the commit.

## Implementation Notes

- Install: `uv add --optional dev mypy types-tabulate pre-commit` updates `pyproject.toml` and `uv.lock`.
- Run `uv run mypy utgiftsanalys/` iteratively, fixing errors file by file starting with `db.py` (lowest dependency) and ending with `cli.py` and `ui.py` (highest).
- The `Literal` type for `AmountClassification` requires `from typing import Literal` (available since Python 3.8).
- `sqlite3.Row` does not support generic subscript; under `python_version = "3.11"` typeshed types it as a non-generic `Mapping[str, Any]`. String-key accesses are accepted; index accesses may produce `Any` — cast where the returned value is used in a typed context.
- `dmypy` can be used during development for fast feedback: `uv run dmypy run -- utgiftsanalys/`. The pre-commit hook uses plain `mypy` for determinism.
- Do not add `mypy` to the `ui` or `default` optional-dep groups — it is a dev-only tool.
