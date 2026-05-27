# AGENTS.md

This repo follows the [AGENTS.md](https://agents.md) convention for
LLM-coding-agent instructions. The actual playbook lives in `CLAUDE.md` at
the repo root (auto-loaded by Claude Code) — read that file first.

The detailed testing protocol, conventions, and gotchas are in
**`tests/README.md`**.

## TL;DR for any agent (Cursor, Cline, Aider, Continue, etc.)

1. Read `CLAUDE.md` — the project context and what's fork-specific vs upstream.
2. Read `tests/README.md` — the standard testing procedure (bug-fix flow,
   feature flow, refactor flow), test naming conventions, and forbidden
   patterns.
3. Before editing any module in `cps/`, find the corresponding test in
   `tests/unit/test_<module>.py`. Run it first as your green baseline.
4. Every change ships with a test that would have caught the regression.
   No exceptions for "trivial" fixes — yesterday's trivial fix is today's
   silent failure.
5. Static-analysis tests (read source files, regex for invariants) are the
   dominant style here. They're fast, need no fixtures, and catch the
   "someone removed the guard" class of bug.

## Where things are

- Source under test: `cps/` (Flask app), `scripts/` (CWA helpers)
- Tests: `tests/unit/` (fast, no Docker), `tests/integration/` (Flask
  client + temp DB), `tests/smoke/`, `tests/docker/` (real container)
- Shared fixtures: `tests/conftest.py`
- Test deps: `requirements-dev.txt`

## Running tests

```bash
# fast feedback (no Docker, parallel)
pytest tests/unit/ tests/smoke/ -n auto -x

# focused on a module you touched
pytest tests/unit/test_<module>.py -v

# with coverage
pytest tests/unit/ --cov=cps --cov-report=term-missing
```

If `cps` won't import, you're missing dev deps:
`pip install -r requirements-dev.txt` (or use the venv in `tests/README.md`).

## Branches & shipping

`tasse/main` rebuilds the production container automatically. Land on
`tasse/dev` first, verify CI green, then fast-forward `tasse/main`.
