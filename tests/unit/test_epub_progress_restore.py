# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Static checks for the EPUB reader progress-restore logic.

We don't have a JS test runner wired up in this branch, so these tests
read epub-progress.js as text and verify the fix for the kosync-hint
shadowing bug stays in place. The bug: the locationchange listener was
writing "0" to localStorage during the reader's initial load, before the
restore step ran. On the next restore, that "0" was truthy and shadowed
the kosync hint, so a book that you'd read to 12% on a Kobo / KOReader
device opened at 0% in the webreader.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EPUB_PROGRESS_JS = PROJECT_ROOT / "cps" / "static" / "js" / "reading" / "epub-progress.js"


def _read() -> str:
    return EPUB_PROGRESS_JS.read_text(encoding="utf-8")


class TestRestoreOrder:
    def test_restore_complete_flag_exists(self):
        src = _read()
        # The flag is the gate that prevents pre-restore locationchange events
        # from polluting localStorage.
        assert "let restoreComplete = false" in src or "let restoreComplete=false" in src
        # The flag must be flipped to true after the restore branch decides
        # where to position the reader.
        assert "restoreComplete = true" in src

    def test_localstorage_write_is_gated_on_restore_complete(self):
        src = _read()
        # The save block must check restoreComplete before writing.
        # We look for an early-return on !restoreComplete inside the listener.
        assert "if (!restoreComplete)" in src

    def test_zero_progress_is_not_persisted(self):
        src = _read()
        # The save guard must require newPos > 0 so an at-start position
        # never gets stored. Otherwise restoreComplete=true alone wouldn't
        # save us from the next "locationchange" landing at 0.
        assert "newPos > 0" in src


class TestRestoreSourcePriority:
    def test_saved_progress_treated_as_int_with_zero_fallback(self):
        src = _read()
        # The savedProgress check must coerce to int and fall back to 0 so a
        # stored "0" (legacy data from before the fix) is treated as missing,
        # not as truthy.
        # Look for the parseInt with || "0" fallback pattern.
        assert 'parseInt(localStorage.getItem("calibre.reader.progress.' in src
        assert '|| "0"' in src

    def test_savedprogress_strictly_positive_to_win(self):
        src = _read()
        # The "use savedProgress" branch must require savedProgress > 0,
        # otherwise a 0 value still wins over the kosync hint.
        assert "savedProgress > 0" in src

    def test_kosync_branch_runs_when_no_local_progress(self):
        src = _read()
        # The kosync branch must be the fallback when savedProgress is not > 0
        # and there is no manual CWA bookmark.
        assert "kosyncPercent > 0" in src
        assert "!hasBookmark" in src
        assert "kosyncPercent / 100" in src or "kosyncPercent/100" in src

    def test_no_legacy_truthy_stringcheck_for_savedprogress(self):
        src = _read()
        # Guard against regressing to `if (savedProgress) { ... }` where the
        # string "0" is truthy. The replacement must be a numeric check.
        assert "if (savedProgress)" not in src
