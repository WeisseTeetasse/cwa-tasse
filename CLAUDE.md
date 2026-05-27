# Calibre-Web Automated — Agent Playbook

This file is auto-loaded by Claude Code at session start. Read it before editing.
The same content is mirrored in `AGENTS.md` for non-Claude agents (Cursor, etc.).

For the full testing protocol (commands, conventions, gotchas) see
**`tests/README.md`** — that file is the source of truth and updated more often
than this one.

---

## What this repo is

A fork-of-a-fork: upstream **Calibre-Web** → **Calibre-Web-Automated (CWA)** by
crocodilestick → **WeisseTeetasse/cwa-tasse** (this fork). Most code in `cps/`
is upstream; the fork-specific additions are:

- `cps/hardcover_state_sync.py`, `cps/services/hardcover.py`,
  `cps/tasks/hardcover_*.py`, `cps/metadata_provider/hardcover.py`
- `cps/progress_syncing/` (kosync/KOReader protocol, checksums, models)
- `cps/readingservices.py` (Kobo native sync intercept, EPUB progress mapping)
- `cps/magic_shelf.py` (dynamic/smart shelves)
- `cps/internal_auth.py`, security additions in `cps/usermanagement.py`,
  `cps/kobo_auth.py`, `cps/web.py` (password reset, rate limits, token revoke)
- `cps/utils/filename_sanitizer.py`, `cps/utils/text_similarity.py`
- `cps/kobo_cover_cache.py`, `cps/duplicates.py` (timezone-aware)
- `cps/services/background_scheduler.py` (per-job IDs, replace_existing)
- `cps/cwa_functions.py` (CWA-specific tasks/notifications)

When in doubt about whether something is fork-specific: `git log -- <path>`
and look at the author. Upstream commits come from `crocodilestick` or the
original Calibre-Web maintainers; fork additions have your commits on top.

## Branches

- `tasse/main` — what production runs. **Container rebuilds automatically on push.**
- `tasse/dev` — staging. Land here first, verify, then merge to `main`.
- `origin/main` (crocodilestick) — upstream, periodically merged into `tasse/dev`.

**Default flow:** branch from `tasse/dev`, PR/merge to `tasse/dev`, then
fast-forward `tasse/main` to `tasse/dev` once verified.

## Before changing anything

1. **Read `tests/README.md` § "Standard procedure"** — the bug-fix /
   new-feature / refactor checklists are there.
2. **Find the matching test file.** Conventionally `tests/unit/test_<module>.py`
   or `tests/unit/test_<feature>_<aspect>.py`. If one exists, run it first to
   confirm it passes on green main before you start editing — that's your
   regression baseline.
3. **If no test file exists for the module you're touching, create one
   *before* the fix.** Even a single static-analysis test pinning the current
   behavior. Future regressions will catch themselves.

## Mandatory checklist for every change

- [ ] Test added or updated that would have caught the bug / proves the
      feature works
- [ ] Test name encodes the bug — `test_<module>_<scenario>_<expected>` or
      `test_regression_<short_bug_description>`
- [ ] `pytest tests/unit/ -x` passes locally
- [ ] No `except Exception: pass` added — if you must swallow, log at WARNING
      with context (see `tests/README.md` § "Forbidden patterns")
- [ ] No new `verify=False` in `requests.*` calls
- [ ] No new bare `print()` for logging — use `log = logger.create()`
- [ ] If you added a route: it has a permission decorator
      (`@user_login_required`, `@login_required_if_no_ano`, `@admin_required`,
      or `@requires_kobo_auth`)
- [ ] If you added an internal API endpoint: it's gated by
      `cps.internal_auth.require_internal_token`
- [ ] If you added a config column: it has an idempotent migration in
      `migrate_user_table` / `migrate_*_table` using `exists().where(column)`

## Forbidden / red-flag patterns

These will be caught by `tests/unit/test_repo_invariants.py` and CI. Don't add them:

- `except Exception: pass` (silent swallow) — log it, even if you re-raise
- `requests.get(..., verify=False)` / `verify=False` anywhere outside tests
- `eval(` / `exec(` on any user-derived string
- Persisting Flask session via `session.permanent = True` on Kobo / API routes
- New endpoints without auth decorators
- New scheduler jobs without a stable `job_id`
- Bare `subprocess.run(..., shell=True)` with f-string interpolation of user data
- Editing `cps/cw_login/` or `cps/cw_advocate/` — these are vendored, leave alone

## When you touch X, run Y

| Touched | Run | Why |
|---|---|---|
| `cps/hardcover_state_sync.py`, `cps/services/hardcover.py` | `pytest tests/unit/test_hardcover*` | Sync conflicts, rate limits |
| `cps/schedule.py`, `cps/services/background_scheduler.py` | `pytest tests/unit/test_hardcover_sync_schedule.py` | Per-user job IDs, replace_existing |
| `cps/progress_syncing/`, `cps/readingservices.py` | `pytest tests/unit/test_progress* tests/unit/test_kosync* tests/unit/test_kobo*` + `tests/integration/test_kosync*` | EPUB↔KOReader↔Kobo progress mapping |
| `cps/web.py` auth / `cps/usermanagement.py` / `cps/kobo_auth.py` | `pytest tests/unit/test_security_hardening.py tests/unit/test_internal_auth.py` | Rate limits, token revocation, password reset |
| `cps/admin.py` | `pytest tests/unit/test_security_hardening.py tests/unit/test_hardcover_sync_schedule.py` | Admin password change must revoke Kobo tokens; delete-user must unschedule jobs |
| `cps/internal_auth.py`, `cps/cwa_functions.py` | `pytest tests/unit/test_internal_auth.py tests/unit/test_internal_api_url.py` | HMAC shared token between CWA processes |
| `cps/static/js/reading/epub-progress.js` | `pytest tests/unit/test_epub_progress_restore.py` | localStorage race on initial load |
| `cps/ub.py` (schema) | All `tests/unit/test_*` + smoke tests | Migrations are idempotent and run on boot |
| `cps/duplicates.py` | `pytest tests/unit/test_duplicates_timezone.py` | Timezone-aware mtime comparisons |
| `cps/magic_shelf.py` | `pytest tests/unit/test_magic_shelf.py` | Rule normalization, system shelves |

## When something silently doesn't work

Hardcover state sync not firing was a `try/except Exception: pass` in
`_schedule_hardcover_state_sync` that ate a `NameError` for ~weeks. The lesson
isn't "remove the try/except"; it's: **if you wrap something in try/except,
the except branch logs at WARNING with the exception**. Tests in
`tests/unit/test_hardcover_sync_schedule.py::TestSilentSwallowingRemoved`
enforce this for that one function — add similar checks if you wrap a new
boot-time function.

## How tests are written here

- **Static-analysis tests** dominate. They read source files and `re.search`
  for invariants. No Flask app, no DB. Fast, zero setup. Catch "someone
  removed the fix."
- **Behavioral tests** for pure functions (no Flask). See
  `test_filename_sanitizer.py`, `test_text_similarity.py`,
  `test_kobo_cover_cache.py`.
- **Real Flask client tests** only for `tests/integration/` — they're slower
  and need fixtures.
- **Docker e2e** under `tests/docker/` — only for things that need a real
  container (ingest pipeline, schema migrations on a live DB).

Pattern for a regression test after a bug fix:

```python
class TestRegressionHardcoverScheduleNotFiring:
    """Bug: enabling state-sync from UI didn't register a scheduler job
    until container restart. Root cause: _schedule_hardcover_state_sync
    ran only at boot. Fix: per-user helper called from change_profile."""

    def test_change_profile_reregisters_hardcover_job(self):
        src = _read(WEB)
        assert "schedule_hardcover_state_sync_for_user(current_user)" in src
```

The docstring explains the bug so the next LLM doesn't "simplify away" the
fix without understanding it.

## Common gotchas

- **Don't call `create_app()` in tests.** It writes `app.db` to cwd and
  loads the real config. Static-analysis tests don't need it; behavioral
  tests should use the fixtures in `tests/conftest.py`.
- **Don't `pip install` into the system Python.** Use the venv at
  `/tmp/cwa-venv` (auto-recreated if missing — see `tests/README.md`).
- **Translation bot commits** land on `tasse/main` autonomously. After
  pushing to `dev`, you may need to `git fetch tasse && git merge tasse/main`
  before pushing to `tasse/main`.
- **APScheduler job IDs must be stable.** Per-user jobs use the format
  `hardcover_state_sync_user_<id>`. Always pass `replace_existing=True` when
  re-registering — otherwise APScheduler raises `ConflictingIdError`.
- **Kobo `requires_kobo_auth` must keep `remember=False`**. Setting it to
  True would issue a persistent cookie that survives auth-token revocation.

## When the user says "push a fix"

They mean to `tasse/main` (production), not just `tasse/dev`. The flow:

```bash
git checkout dev && git push tasse dev
git checkout main && git merge --ff-only dev && git push tasse main
# or, when main has bot commits ahead of dev:
git fetch tasse && git merge tasse/main && git push tasse main
```

The container rebuilds from `tasse/main` automatically via GitHub Actions.
Verify the build at https://github.com/WeisseTeetasse/cwa-tasse/actions
before declaring "shipped."
