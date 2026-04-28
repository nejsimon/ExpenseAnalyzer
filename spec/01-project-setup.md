# 01 — Project Setup

**Status:** [ ] todo

## Description

Initial project scaffolding: `pyproject.toml`, `CLAUDE.md`, Python package skeleton, `data/` directory, and empty module stubs.

## Acceptance Criteria

- `pip install -e ".[dev]"` succeeds without errors.
- `utgiftsanalys --help` prints the command overview.
- All module files exist and can be imported without error.

## Implementation Notes

- Flat package layout: `utgiftsanalys/` at project root (no `src/` wrapper).
- Entry point: `utgiftsanalys = "utgiftsanalys.cli:main"` in `[project.scripts]`.
- Build backend: `hatchling`.
- Dependencies: `click`, `chardet`, `holidays`, `tabulate`.
- Dev dependencies: `pytest`, `pytest-cov`.
- `data/` directory holds the SQLite file; add to `.gitignore`.
