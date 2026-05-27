# Testing Protocol — Calibre-Web Automated (cwa-tasse fork)

This file is the **source of truth** for how tests work in this repo and the
standard procedure for adding tests when you change something. Both human
contributors and LLM agents (see `../CLAUDE.md` and `../AGENTS.md`) should
follow it.

> If you're an LLM picking this up cold: read this whole file before editing
> any test file or any production file in `cps/`. It will save you and the
> user a lot of debugging time.

---

## 0. Philosophy

**Tests here are a regression net, not a coverage trophy.** Most tests in
this repo are short, fast, and pinned to a specific past bug or a specific
documented invariant. If you delete a test, ask why it existed — the
docstring at the top of the file usually points to the bug it caught.

Three test styles, in descending order of preference:

1. **Static-analysis tests** (most common) — read source files and use
   `re.search` / `in` to assert invariants. No Flask app, no DB, no
   mocking. Catch "someone removed the fix" and "someone copied the bad
   pattern again." Run in <1 second.
2. **Pure-function behavioral tests** — call functions that don't need
   Flask context (`cps.utils.*`, `cps.kobo_cover_cache`,
   `cps.progress_syncing.checksums.*`). Real input/output.
3. **Flask test-client tests** — only when behavior requires routing,
   auth, or session state. Use the fixtures in `conftest.py`.

Avoid:
- Tests that need a real Calibre library
- Tests that hit the network
- Tests with `time.sleep()` for synchronization

---

## 1. Quick start

### Install (one-time)

```bash
# Recommended: dedicated venv at /tmp/cwa-venv (works around system Python)
python3.13 -m venv /tmp/cwa-venv
/tmp/cwa-venv/bin/pip install -r requirements-dev.txt
/tmp/cwa-venv/bin/pip install Flask-Dance  # required by some upstream imports

# To run tests:
/tmp/cwa-venv/bin/pytest tests/unit/ -n auto -x
```

If the venv was wiped (we're working in worktrees) recreate it with the
two commands above — they take ~30 seconds.

### Run the right subset

| Goal | Command |
|---|---|
| Fast feedback before commit | `pytest tests/unit/ tests/smoke/ -n auto -x` |
| Focused module work | `pytest tests/unit/test_<module>.py -v` |
| Just one test | `pytest tests/unit/test_x.py::TestClass::test_fn -v` |
| All static-analysis tests | `pytest tests/unit/ -n auto` (they're ~all static) |
| With coverage | `pytest tests/unit/ --cov=cps --cov-report=term-missing` |
| Including integration (slow) | `pytest tests/ -n auto --ignore=tests/docker` |
| Full suite incl. Docker | `pytest tests/` (needs Docker daemon) |

---

## 2. Standard procedure

These are the three flows you should run through for every change. Pick
the one that matches.

### 2A. Bug-fix flow

When the user reports something broken, or you found a bug:

1. **Reproduce in a test FIRST.** Write a failing test that encodes the
   bug before you write the fix. The test name encodes what was broken:
   ```python
   class TestRegressionHardcoverScheduleNotFiring:
       """Bug: enabling state-sync from UI didn't register a scheduler
       job until container restart. Root cause: …. Fix: ….
       """
       def test_change_profile_reregisters_hardcover_job(self):
           ...
   ```
2. **Confirm the test fails on broken main** (so you know it actually
   catches the bug). Skip this only when the bug is "the file doesn't
   exist yet."
3. **Write the smallest fix that makes the test pass.**
4. **Run the full unit suite** to confirm no regressions.
5. **Commit message format**:
   `fix(<area>): <short imperative>` followed by a body that explains
   the symptom, root cause, and fix. See commit `39c4aae` for a
   reference shape.

### 2B. New-feature flow

1. **Write a test that pins the new behavior** — even if it's just a
   static-analysis test asserting the new function exists and has the
   right signature. This documents the contract.
2. **Implement.**
3. **Add at least one behavioral test** for non-trivial logic (anything
   beyond a wiring change).
4. **Add a row to the "When you touch X, run Y" table in `CLAUDE.md`** so
   future changes in the same area know which tests to run.
5. **If the feature crosses module boundaries** (e.g. new route in
   `web.py` that calls a helper in `helper.py` that touches `ub.py`),
   add invariants in `test_repo_invariants.py` for any forbidden patterns
   you're introducing guards against.

### 2C. Refactor flow

1. **Snapshot current behavior with tests** (if not already covered).
   You will regret refactoring without them.
2. **Make the change.**
3. **Tests must still pass without modification** — that's what makes it
   a refactor and not a behavior change.
4. **If you have to modify a test to make it pass, STOP.** That's a
   behavior change, not a refactor. Re-frame the work, get a clear
   answer from the user, and update the relevant section above.

---

## 3. Naming & file organization

### Test file names

- `test_<module>.py` — covers `cps/<module>.py` (e.g. `test_helper.py`)
- `test_<feature>_<aspect>.py` — covers a feature spanning modules
  (e.g. `test_hardcover_sync_schedule.py`, `test_security_hardening.py`)
- `test_regression_<short>.py` — only when a single bug is large enough
  to warrant its own file. Usually fold into an existing
  `Test<Bug>` class instead.

### Test class & function names

```python
class TestFeatureArea:
    """One-line description of what this class pins down.

    Bug context (if regression-pinned): describe the original failure
    so future LLMs understand why the assertion looks weird.
    """

    def test_<unit>_<scenario>_<expected>(self):
        # e.g. test_change_profile_reregisters_hardcover_job
        # or  test_basic_auth_records_failure_on_bad_password
        ...
```

Prefer `Test<Area><Behavior>` class names over `Test<File>`. Group by
behavior, not by source-file mirroring.

### Markers

Already registered in `conftest.py`:

```python
@pytest.mark.unit              # fast, no Docker, no network
@pytest.mark.smoke             # critical happy-path
@pytest.mark.slow              # >5s — keep out of fast feedback loop
@pytest.mark.requires_docker   # needs running container
@pytest.mark.requires_calibre  # needs calibredb / ebook-convert binary
@pytest.mark.docker_integration
@pytest.mark.docker_e2e
```

Module-level default for `tests/unit/`:

```python
pytestmark = pytest.mark.unit
```

---

## 4. The static-analysis pattern

This is the dominant style here. Skeleton:

```python
"""Static checks for <feature>.

Bug we fixed: <one paragraph explaining what was broken>.
Why these assertions exist: <what regression they prevent>.
"""

import re
from pathlib import Path
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEDULE = PROJECT_ROOT / "cps" / "schedule.py"
# ... other paths


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestFeatureWiring:
    def test_helper_exists(self):
        src = _read(SCHEDULE)
        assert "def schedule_hardcover_state_sync_for_user(" in src
        assert "replace_existing=True" in src
```

Why this works:
- No imports of `cps.*` — survives missing optional deps
- Catches deletion of the fix, removal of decorators, copy-paste of bad
  patterns into a new file
- Survives upstream merges because it's pinned to fork-specific lines

When the static-analysis test isn't enough:
- The bug is in branching logic, not in whether the code exists
- Behavior depends on input values
- The regression would still pass the regex but fail in practice

For those, write a behavioral test against a pure helper if possible. If
the helper requires Flask context, refactor the production code to
extract the pure part — that's the right move anyway.

---

## 5. Forbidden patterns

These are checked by `tests/unit/test_repo_invariants.py`. Don't add them.
If you legitimately need one, document why in the test and exempt the
specific file with a constant.

| Pattern | Why forbidden | Use instead |
|---|---|---|
| `except Exception: pass` | Silent failures hid the Hardcover bug for weeks | Log at WARNING with the exception |
| `verify=False` in `requests.*` | TLS bypass | Configure CA bundle properly |
| `eval(` / `exec(` on user input | RCE | Parse explicitly |
| New route without `@*_required` decorator | Auth bypass | Add the right decorator |
| Scheduler `add_job` without `id=` | Can't replace job on settings change | Pass stable `job_id` |
| `session.permanent = True` on API routes | Persistent cookie for ephemeral auth | Leave default |
| Editing `cps/cw_login/` or `cps/cw_advocate/` | Vendored upstream | Leave alone, monkeypatch if needed |
| `print(` for logging in `cps/` | Lost on production | `log = logger.create()` |

---

## 6. Critical paths & their tests

The "When you touch X, run Y" table in `CLAUDE.md` is authoritative.
Below is the inverse — for each critical fork feature, the tests that
guard it:

### Hardcover sync (state + progress)

- `tests/unit/test_hardcover_state_sync_conflicts.py` — duplicate
  detection, status promotion ladder
- `tests/unit/test_hardcover_progress_sync.py` — % rounding, "finished"
  threshold, rate-limit backoff
- `tests/unit/test_hardcover_sync_schedule.py` — per-user APScheduler
  jobs, stable IDs, replace_existing, profile-save re-registration,
  delete-user unschedule
- `tests/unit/test_hardcover_service.py` — `HardcoverClient` invariants
  (markdown escaping, GraphQL error handling)
- `tests/unit/test_hardcover_tasks.py` — `CalibreTask` subclasses,
  session cleanup in finally blocks

### Kobo native sync

- `tests/unit/test_kobo_cover_image_id.py` — cover cache-busting via mtime
- `tests/unit/test_kobo_cover_cache.py` — `normalize_cover_uuid`,
  `build_cover_image_id` behavior
- `tests/unit/test_kobo_multi_device_sync.py` — per-device sync token
  isolation
- `tests/unit/test_kobo_sync_timestamps.py` — timestamp precision /
  rounding
- `tests/unit/test_kobo_auth_hardening.py` — `remember=False`, post-
  password-change revocation

### Progress sync (kosync / KOReader)

- `tests/unit/test_kosync_helpers.py`, `test_progress_syncing_*` —
  protocol, models, checksums
- `tests/integration/test_progress_syncing_kosync.py`,
  `test_kosync_edge_cases.py`, `test_kosync_update_read_status.py` —
  full HTTP flows
- `tests/unit/test_epub_progress_restore.py` — localStorage race fix in
  the webreader
- `tests/unit/test_readingservices_routes.py` — annotation/storage
  endpoints, auth gating

### Auth & security

- `tests/unit/test_security_hardening.py` — per-IP rate limits, CSRF on
  cancel, password-reset token TTL, Kobo token revocation on password
  change
- `tests/unit/test_internal_auth.py`, `test_internal_api_url.py` — HMAC
  shared token between CWA processes

### Ingest / Calibre integration

- `tests/unit/test_author_sort_helpers.py`, `test_calibre_init.py`,
  `test_jinjia_filters.py`, `test_cwa_db.py`, `test_helper.py`
- `tests/integration/test_ingest_*` — file-drop → library
- `tests/smoke/test_*_smoke.py` — startup, migration safety

### Magic shelves

- `tests/unit/test_magic_shelf.py` — rule normalization, system shelf
  templates, query builder safety

### Misc fork additions

- `tests/unit/test_duplicates_timezone.py` — naïve vs aware datetime
  comparison
- `tests/unit/test_cwa_update_notifications.py` — notification
  rendering, dismissal persistence
- `tests/unit/test_durable_job_queue.py` — job persistence across
  process restart
- `tests/unit/test_oauth_session.py` — OAuth session handling
- `tests/unit/test_filename_sanitizer.py`,
  `test_text_similarity.py` — pure helpers
- `tests/unit/test_repo_invariants.py` — global forbidden-pattern guard

---

## 7. Coverage

```bash
pytest tests/unit/ --cov=cps --cov=scripts --cov-report=term-missing
pytest tests/unit/ --cov=cps --cov-report=html  # open htmlcov/index.html
```

Coverage targets (informational — don't chase the number):
- Fork-added modules: aim for ≥70% with regression tests on every
  reported bug
- Upstream-derived modules: don't add coverage just for coverage's sake.
  Only test what we've modified or what's critical to fork features.

---

## 8. Common gotchas

- **`create_app()` in tests writes `app.db` to cwd.** Don't call it.
  Static-analysis tests don't need a Flask app; use the fixtures in
  `conftest.py` for the few cases that do.
- **`sys.path` is set up by `conftest.py`.** Don't `sys.path.insert(0, ...)`
  inside individual test files — you'll fight the fixture.
- **`unidecode` is optional.** Don't write tests that fail if it's
  missing; gate with `pytest.importorskip("unidecode")` if needed.
- **Static-analysis regex must use raw strings + `re.DOTALL` for
  multi-line.** Single-line `^` / `$` won't match what you think.
- **Worktree paths.** This repo uses `git worktree`. Path
  `tests/unit/test_x.py` resolves relative to the worktree root, not
  the main checkout. The `PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent`
  pattern handles this correctly.
- **`pytest-xdist` (`-n auto`) reorders tests.** Don't write tests that
  depend on order. Each test should be self-contained.
- **Translation bot.** `crocodilestick/Calibre-Web-Automated` translation
  bot lands commits on `tasse/main` autonomously when changes flow up.
  After pushing to `dev` you may need `git fetch tasse && git merge tasse/main`
  before pushing to `tasse/main`. This is normal — don't force-push.

---

## 9. Adding a new test file: minimum template

```python
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""<One-paragraph description of what this file pins down.>

<If this is a regression test, the bug:>
- Symptom: <what the user saw>
- Root cause: <what was actually wrong>
- Fix (commit <sha>): <what we did>
"""

from pathlib import Path
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestFeatureBehavior:
    def test_x_does_y_when_z(self):
        ...
```

Copy that, fill in, run `pytest tests/unit/test_yourfile.py -v`.

---

## 10. When tests fail in CI but pass locally

1. Make sure you're on the right Python (3.13).
2. Make sure you reinstalled deps: `pip install -r requirements-dev.txt`.
3. Make sure you're not running `pytest` from a different cwd than the
   repo root — `PROJECT_ROOT` resolution depends on the file's location,
   not cwd, so this rarely matters but it can.
4. Check if a worktree leftover is shadowing the import:
   `find . -name "*.pyc" -delete && find . -name __pycache__ -exec rm -rf {} +`
5. If a Docker integration test fails: check `docker ps` and the
   container logs. Don't retry blindly.

---

## 11. Help

- Project Discord: https://discord.gg/EjgSeek94R (upstream CWA)
- This fork: https://github.com/WeisseTeetasse/cwa-tasse
- Test fixtures: see `tests/fixtures/README.md`
