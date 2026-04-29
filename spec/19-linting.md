# 19 — Linting

**Status:** [ ] pending

## Description

Introduce ruff as the project linter and formatter, configure a selected rule set targeting zero violations, and add a pre-commit hook that blocks commits on any linting or formatting failure.

## Acceptance Criteria

- `uv run ruff check utgiftsanalys/` exits 0 on the current source tree.
- `uv run ruff format --check utgiftsanalys/` exits 0 on the current source tree.
- `[tool.ruff]` and `[tool.ruff.lint]` sections exist in `pyproject.toml`.
- All pre-existing violations are fixed — not suppressed with `# noqa` — unless suppression is genuinely the only option, in which case the comment must include an explanation.
- `.pre-commit-config.yaml` (created in spec 18 or here if standalone) includes `ruff-check` and `ruff-format` hooks.
- `git commit` fails if ruff reports any linting or formatting issue.

## Tool Choice

**ruff** is chosen because:
- Developed by Astral — the same team as uv — giving a coherent, fast toolchain.
- 10–100× faster than flake8, with no meaningful penalty for running on every commit.
- Replaces flake8, isort, pyupgrade, pep8-naming, flake8-bugbear, and flake8-simplify in a single binary with unified configuration.
- First-class `pyproject.toml` support; no separate `.flake8` or `setup.cfg` needed.
- `ruff format` is Black-compatible and eliminates the need for a separate formatter.

## pyproject.toml Changes

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "mypy>=1.10",       # from spec 18
    "types-tabulate",   # from spec 18
    "pre-commit>=3.7",  # from spec 18
    "ruff>=0.4",
]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "N"]
# E   — pycodestyle errors
# F   — pyflakes (undefined names, unused imports)
# W   — pycodestyle warnings
# I   — isort (import ordering)
# UP  — pyupgrade (use modern Python syntax)
# B   — flake8-bugbear (likely bugs and design issues)
# SIM — flake8-simplify (simplifiable code constructs)
# N   — pep8-naming (naming conventions)

[tool.ruff.lint.isort]
known-first-party = ["utgiftsanalys"]
```

`line-length = 100` matches the existing code style (several lines in `output.py` and `ui.py` exceed 88 characters).

## Auto-fix Workflow (one-time, on first implementation)

```bash
uv run ruff check --fix utgiftsanalys/
uv run ruff format utgiftsanalys/
uv run pytest   # confirm no logic was altered
```

Review the diff before committing: ruff's auto-fixes are mechanical (import reordering, trailing whitespace, quote normalization, simple refactors). Any B or SIM fix that changes logic should be inspected manually.

## Known Violation Categories to Fix

Based on the reviewed source files:

**I (isort)** — relative imports in each module should be grouped after standard-library and third-party imports. `ruff check --fix` handles this automatically.

**UP (pyupgrade)** — any remaining `Optional[X]` or `Union[X, Y]` forms in older files should be replaced with `X | None` and `X | Y`. Also catches `dict()` → `{}`, `list()` → `[]` where applicable.

**B (bugbear)** — `B007` flags loop variables that are assigned but never used in the loop body (should be `_`). Review `ui.py` and `importer.py`.

**SIM (simplify)** — `SIM108` may flag `if/else` blocks that can be written as a ternary; accept or suppress if readability suffers.

**N (naming)** — `N806` flags variables in function scope that use `CamelCase` (should be `snake_case`). The single-letter variable `l` in any loop body should be renamed to `line` or similar (ambiguous with `1` and `I`).

**E/W** — trailing whitespace, extra blank lines, line-length violations. All auto-fixed by `ruff format`.

**F (pyflakes)** — verify no unused imports remain after spec 17–18 work.

## Pre-commit Configuration

If `.pre-commit-config.yaml` was created by spec 18, extend it. Otherwise create it from scratch. Final file:

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

      - id: ruff-check
        name: ruff lint
        language: system
        entry: uv run ruff check utgiftsanalys/
        types: [python]
        pass_filenames: false

      - id: ruff-format
        name: ruff format check
        language: system
        entry: uv run ruff format --check utgiftsanalys/
        types: [python]
        pass_filenames: false
```

The `ruff-check` hook does **not** use `--fix` — hooks that silently modify staged files are surprising. Instead, the developer runs `ruff check --fix && ruff format` locally, re-stages the changes, then commits.

## Implementation Notes

- Install: `uv add --optional dev ruff` updates `pyproject.toml` and `uv.lock`.
- Run `uv run pre-commit install` (or re-run if the hook was already installed for spec 18) to register the updated hook file.
- To check only without auto-fix (mirrors what CI/pre-commit does): `uv run ruff check utgiftsanalys/`.
- To check formatting only: `uv run ruff format --check utgiftsanalys/`.
- `ruff format` is Black-compatible; if Black is ever added as a dependency, remove it — one formatter is enough.
- The `tests/` directory is not in the `select` scope because test files legitimately use bare `assert` statements (flagged by `S101` if that rule were enabled). Since `S` (bandit) is not in the selected rule set, this is not a concern; no exclusion needed.
- After the initial `--fix` pass, run `uv run pytest` to confirm tests still pass before committing.
