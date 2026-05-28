# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression test for the SystemExit-not-caught bug in
``cps.progress_syncing.settings.is_koreader_sync_enabled``.

Symptom (before fix): when /config/app.db was unavailable,
scripts/generate_book_checksums.py would silently exit with no error
message and process no books. The user would see "ran fine" but no
checksums got written.

Root cause: ``CWA_DB.connect_to_db`` calls ``sys.exit(0)`` on connect
failure — that raises SystemExit, which is a BaseException, NOT an
Exception. The ``except Exception:`` in is_koreader_sync_enabled didn't
catch it, so the SystemExit propagated up and silently terminated the
caller.

Fix: catch BaseException so SystemExit is included.
"""

import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS = PROJECT_ROOT / "cps" / "progress_syncing" / "settings.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestRegressionSystemExitCaught:
    def test_settings_module_catches_baseexception(self):
        src = _read(SETTINGS)
        body = re.search(
            r"def is_koreader_sync_enabled\(.*?\n(.*?)(?=\ndef |\Z)",
            src,
            re.DOTALL,
        )
        assert body, "Could not locate is_koreader_sync_enabled body"
        assert "except BaseException" in body.group(1), (
            "is_koreader_sync_enabled must catch BaseException (not just "
            "Exception) — CWA_DB.connect_to_db calls sys.exit(0) on "
            "connect failure, which is a SystemExit and would propagate "
            "through `except Exception:` and silently abort the caller."
        )


class TestBehaviorReturnsFalseOnMissingDb:
    """Direct behavioral check: with no /config/app.db and the cwa_db
    import working, the function should return False rather than
    propagating SystemExit."""

    def test_returns_false_without_crashing(self):
        # We can't easily run this from a worktree because the production
        # cwa_db module hardcodes /config paths. So we monkey-patch
        # CWA_DB to raise SystemExit, mimicking the bug condition.
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        sys.path.insert(0, str(PROJECT_ROOT))

        # Import the helper (it doesn't need cwa_db at import time —
        # only at call time)
        from cps.progress_syncing.settings import is_koreader_sync_enabled

        # Inject a CWA_DB that raises SystemExit when called, like the
        # real one does on connect failure
        import cps.progress_syncing.settings as settings_mod
        import types

        fake_cwa_db = types.ModuleType("cwa_db")
        def _fake_init(self, verbose=False):
            import sys as _sys
            _sys.exit(0)  # mimic real CWA_DB.connect_to_db failure path
        fake_cwa_db.CWA_DB = type("CWA_DB", (), {"__init__": _fake_init})

        snapshot = sys.modules.get("cwa_db")
        sys.modules["cwa_db"] = fake_cwa_db
        try:
            result = is_koreader_sync_enabled()
        finally:
            if snapshot is None:
                sys.modules.pop("cwa_db", None)
            else:
                sys.modules["cwa_db"] = snapshot

        # If the bug were back, this assertion would never even run —
        # the SystemExit would have killed the test process.
        assert result is False
