# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Static invariants for cps/tasks/hardcover_*.py task wrappers.

Past regressions these guard against:
- TaskHardcoverProgressPush used to leak DB sessions when the worker
  raised — added a finally block that calls session.remove() on both
  calibre_db and ub.
- Tasks that ignore the `errors` field of the underlying sync result
  appear as "Success" in the UI but did nothing. State sync must call
  _handleError when result['errors'] is non-empty.
- New CalibreTask subclasses must override `name` and `is_cancellable`
  so the tasks UI renders correctly.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PUSH = PROJECT_ROOT / "cps" / "tasks" / "hardcover_progress_push.py"
STATE = PROJECT_ROOT / "cps" / "tasks" / "hardcover_state_sync.py"
AUTO_ID = PROJECT_ROOT / "cps" / "tasks" / "auto_hardcover_id.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestProgressPushTaskHygiene:
    def test_inherits_calibre_task(self):
        src = _read(PUSH)
        assert "class TaskHardcoverProgressPush(CalibreTask)" in src

    def test_overrides_name_and_cancellable(self):
        src = _read(PUSH)
        assert "def name(" in src
        assert "def is_cancellable(" in src

    def test_run_has_finally_session_cleanup(self):
        """The worker pool reuses threads — a leaked DB session means the
        next task on this thread sees stale data."""
        src = _read(PUSH)
        run_fn = re.search(
            r"def run\(self.*?\n(.*?)(?=\nclass |\Z)",
            src,
            re.DOTALL,
        )
        assert run_fn
        body = run_fn.group(1)
        assert "finally:" in body
        assert "calibre_db.session.remove" in body
        assert "ub.session.remove" in body

    def test_run_logs_exceptions_with_context(self):
        src = _read(PUSH)
        run_fn = re.search(
            r"def run\(self.*?\n(.*?)(?=\nclass |\Z)",
            src,
            re.DOTALL,
        )
        body = run_fn.group(1)
        # No bare swallow — must log
        assert "log.error" in body
        # Must include user_id and book_id in the log context
        assert "user_id" in body
        assert "book_id" in body


class TestStateSyncTaskReportsErrors:
    def test_inherits_calibre_task(self):
        src = _read(STATE)
        assert "class TaskHardcoverStateSync(CalibreTask)" in src

    def test_overrides_name_and_cancellable(self):
        src = _read(STATE)
        assert "def name(" in src
        assert "def is_cancellable(" in src

    def test_propagates_errors_field_to_handle_error(self):
        """If the underlying sync returned errors=[...], the task must
        call _handleError, not _handleSuccess. Otherwise the UI shows
        green and the user thinks sync worked."""
        src = _read(STATE)
        run_fn = re.search(
            r"def run\(self.*?\n(.*?)(?=\nclass |\Z)",
            src,
            re.DOTALL,
        )
        assert run_fn
        body = run_fn.group(1)
        assert 'result.get("errors")' in body or "result.get('errors')" in body
        assert "_handleError" in body
        # The _handleSuccess path must be inside an else branch — not
        # unconditional
        assert "else:" in body


class TestNoSilentSwallow:
    """As with the rest of the Hardcover stack."""

    @pytest.mark.parametrize("path", [PUSH, STATE, AUTO_ID])
    def test_no_bare_except_pass(self, path):
        src = _read(path)
        # Allow `except Exception: pass` only inside finally cleanup
        # blocks (best-effort session.remove) where logging would be noise.
        # The session.remove() cleanup is in a finally — count those
        # specific lines:
        offenders = []
        for m in re.finditer(r"except\s+Exception:\s*\n\s*pass\b", src):
            # Look at the ~6 lines before to see if we're in a session
            # cleanup block
            context = src[max(0, m.start() - 200):m.start()]
            if "session.remove" not in context:
                offenders.append(m.start())
        assert not offenders, (
            f"Bare `except Exception: pass` outside session cleanup at "
            f"offsets {offenders} in {path.name}"
        )
