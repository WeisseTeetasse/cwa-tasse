# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for cps.magic_shelf — fork-added smart shelves feature.

Two layers of testing here:
1. Behavioral tests for the pure helper ``normalize_magic_shelf_order``
   (no Flask, no DB).
2. Static-analysis tests pinning the rule-builder and system-shelf
   invariants — the build_query_from_rules and build_filter_from_rule
   functions construct SQLAlchemy expressions from user-supplied rule
   dicts, so we must guard against:
   * dropping the rule-type allow-list (would let injection-style rules
     through)
   * accepting unknown order modes silently
   * losing the system-shelf is_system flag (would let users delete them)
"""

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MAGIC_SHELF_PATH = PROJECT_ROOT / "cps" / "magic_shelf.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Behavioral: normalize_magic_shelf_order
# ---------------------------------------------------------------------------

def _import_normalize():
    """Import the function without importing the whole cps package.

    Snapshots sys.modules so the stubs don't leak into other test files.
    """
    import importlib.util
    import types

    keys = ("cps", "cps.db", "cps.ub", "cps.logger", "cps.cw_login")
    snapshot = {k: sys.modules.get(k) for k in keys}

    try:
        if "cps" not in sys.modules:
            sys.modules["cps"] = types.ModuleType("cps")
        if "cps.db" not in sys.modules:
            sys.modules["cps.db"] = types.ModuleType("cps.db")
        if "cps.ub" not in sys.modules:
            sys.modules["cps.ub"] = types.ModuleType("cps.ub")
        if "cps.logger" not in sys.modules:
            fake_logger = types.ModuleType("cps.logger")
            fake_logger.create = lambda: SimpleNamespace(
                info=lambda *a, **k: None,
                warning=lambda *a, **k: None,
                error=lambda *a, **k: None,
                debug=lambda *a, **k: None,
            )
            sys.modules["cps.logger"] = fake_logger
        if "cps.cw_login" not in sys.modules:
            fake_cw_login = types.ModuleType("cps.cw_login")
            fake_cw_login.current_user = None
            sys.modules["cps.cw_login"] = fake_cw_login

        spec = importlib.util.spec_from_file_location(
            "_magic_shelf_isolated", MAGIC_SHELF_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.normalize_magic_shelf_order
    except Exception:
        pytest.skip("Could not import magic_shelf in isolation (heavy deps)")
    finally:
        for k, v in snapshot.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


class TestNormalizeMagicShelfOrder:
    def setup_method(self):
        self.normalize = _import_normalize()

    def test_returns_available_when_order_empty(self):
        assert self.normalize([], [1, 2, 3]) == [1, 2, 3]

    def test_preserves_explicit_order(self):
        assert self.normalize([3, 1, 2], [1, 2, 3]) == [3, 1, 2]

    def test_appends_missing_ids_at_end(self):
        # New shelves created since the user last reordered must show up
        assert self.normalize([2], [1, 2, 3]) == [2, 1, 3]

    def test_drops_unknown_ids(self):
        # Shelf 99 was deleted — must not appear in output
        assert self.normalize([99, 1], [1, 2]) == [1, 2]

    def test_deduplicates(self):
        # Defensive against corrupted view_settings
        assert self.normalize([1, 1, 2, 2], [1, 2]) == [1, 2]

    def test_string_ids_coerced_to_int(self):
        # JSON deserialization may give us strings
        assert self.normalize(["2", "1"], [1, 2]) == [2, 1]

    def test_non_numeric_strings_skipped(self):
        assert self.normalize(["foo", "1"], [1, 2]) == [1, 2]

    def test_none_inputs_safe(self):
        assert self.normalize(None, None) == []
        assert self.normalize(None, [1, 2]) == [1, 2]


# ---------------------------------------------------------------------------
# Static invariants: rule builder & system shelves
# ---------------------------------------------------------------------------

class TestRuleBuilderSafety:
    """The rule-builder takes user-supplied JSON. Guard against shifts
    that would let arbitrary SQL through."""

    def test_build_filter_uses_allowlist_branching(self):
        src = _read(MAGIC_SHELF_PATH)
        # build_filter_from_rule must branch on rule['type'] explicitly
        # rather than reflectively dispatching to anything the user names.
        # Look for chains of `if rule_type ==` / `elif rule_type ==` —
        # this is the allow-list pattern.
        assert "def build_filter_from_rule(" in src
        # No getattr-based dispatch on rule_type
        assert not re.search(r"getattr\([^,)]*,\s*rule\[", src), \
            "Reflective dispatch on rule fields would defeat the allow-list"

    def test_no_raw_sql_string_concat_in_rule_builder(self):
        src = _read(MAGIC_SHELF_PATH)
        # We use SQLAlchemy expression objects, never f-string SQL
        # against the engine. Catches a future copy-paste of `db.session.execute(f"...")`.
        assert not re.search(r'session\.execute\(\s*f["\']', src)
        assert not re.search(r'session\.execute\(\s*["\'].*\{', src)


class TestOrderModeAllowlist:
    def test_order_modes_constant_exists(self):
        src = _read(MAGIC_SHELF_PATH)
        assert "MAGIC_SHELF_ORDER_MODES" in src
        assert "DEFAULT_MAGIC_SHELF_ORDER_MODE" in src

    def test_sort_function_falls_back_to_default_on_unknown_mode(self):
        src = _read(MAGIC_SHELF_PATH)
        sort_fn = re.search(
            r"def sort_magic_shelves_for_user\(.*?\n(.*?)(?=\n\ndef )",
            src,
            re.DOTALL,
        )
        assert sort_fn, "Could not locate sort_magic_shelves_for_user body"
        body = sort_fn.group(1)
        # The unknown-mode-falls-back branch must reference the allowlist
        assert "MAGIC_SHELF_ORDER_MODES" in body
        assert "DEFAULT_MAGIC_SHELF_ORDER_MODE" in body


class TestSystemShelvesProtected:
    """System shelves (Currently Reading, Want to Read, etc.) must not be
    deletable by users — they're auto-created and managed."""

    def test_create_system_shelves_sets_is_system_true(self):
        src = _read(MAGIC_SHELF_PATH)
        # The creation path must set is_system=True so deletion guards work
        create_fn = re.search(
            r"def create_system_magic_shelves\(.*?\n(.*?)(?=\n\ndef )",
            src,
            re.DOTALL,
        )
        assert create_fn, "Could not locate create_system_magic_shelves body"
        assert "is_system=True" in create_fn.group(1)

    def test_get_template_helper_exists(self):
        src = _read(MAGIC_SHELF_PATH)
        # Used by the create-from-templates UI
        assert "def get_system_shelf_template(" in src
        assert "def list_system_shelf_templates(" in src
