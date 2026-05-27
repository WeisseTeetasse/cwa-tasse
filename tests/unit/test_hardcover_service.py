# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for cps.services.hardcover — the Hardcover GraphQL API client.

Mix of behavioral (escape_markdown, MissingHardcoverToken, identifier
parsing) and static-analysis (TLS, timeout, 401 handling).

Why this file exists: the Hardcover client is the only outbound thing
authenticated with a user-supplied long-lived bearer token. Mistakes
here leak that token (no TLS, logged URLs with token, etc.) or silently
no-op the entire sync (swallowed 401).
"""

import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

HC_PATH = PROJECT_ROOT / "cps" / "services" / "hardcover.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Behavioral tests (importable pure-ish functions)
# ---------------------------------------------------------------------------

def _import_hardcover():
    """Import the module without full app context (avoids cps/__init__.py).

    Snapshots sys.modules so the temporary `cps` / `cps.logger` stubs
    don't leak into later test files (which would break tests that
    import the real cps package).
    """
    import importlib.util
    import sys
    import types

    class _StubLog:
        info = warning = error = debug = staticmethod(lambda *a, **k: None)

    snapshot = {k: sys.modules.get(k) for k in ("cps", "cps.logger")}
    try:
        if "cps" not in sys.modules:
            sys.modules["cps"] = types.ModuleType("cps")
        if "cps.logger" not in sys.modules:
            fake_logger = types.ModuleType("cps.logger")
            fake_logger.create = lambda: _StubLog()
            sys.modules["cps.logger"] = fake_logger
        spec = importlib.util.spec_from_file_location("_hc_service", HC_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        pytest.skip(f"cps.services.hardcover unavailable: {e}")
    finally:
        # Restore — remove stubs we added, restore originals
        for k, v in snapshot.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


class TestEscapeMarkdown:
    def setup_method(self):
        self.hc = _import_hardcover()

    def test_none_returns_none(self):
        assert self.hc.escape_markdown(None) is None

    def test_empty_returns_empty(self):
        assert self.hc.escape_markdown("") == ""

    def test_plain_text_unchanged(self):
        assert self.hc.escape_markdown("hello world") == "hello world"

    def test_escapes_brackets(self):
        # Markdown link syntax must not survive
        assert self.hc.escape_markdown("[evil](url)") == r"\[evil\]\(url\)"

    def test_escapes_html_brackets(self):
        # < > must be escaped to defeat HTML injection on the Hardcover side
        assert "<" not in self.hc.escape_markdown("<script>").replace(r"\<", "")
        assert ">" not in self.hc.escape_markdown("<script>").replace(r"\>", "")

    def test_escapes_backslash_first(self):
        # Order matters — backslash must escape before chars that will be
        # prefixed with one. "a\b" should become "a\\b" not "a\\\\b"
        out = self.hc.escape_markdown(r"a\b")
        assert out == r"a\\b"

    def test_pipe_escaped(self):
        # Pipes break GitHub-flavored markdown tables Hardcover might render
        assert "|" not in self.hc.escape_markdown("a|b").replace(r"\|", "")


class TestMissingHardcoverToken:
    def setup_method(self):
        self.hc = _import_hardcover()

    def test_empty_token_raises_at_construction(self):
        with pytest.raises(self.hc.MissingHardcoverToken):
            self.hc.HardcoverClient(token="")

    def test_none_token_raises_at_construction(self):
        with pytest.raises(self.hc.MissingHardcoverToken):
            self.hc.HardcoverClient(token=None)  # type: ignore[arg-type]

    def test_valid_token_constructs(self):
        client = self.hc.HardcoverClient(token="fake-token-xyz")
        assert "Bearer fake-token-xyz" in client.headers["Authorization"]


class TestEscapeMarkdownEdgeCases:
    """Edge cases that pin observed behavior. Read before refactoring."""

    def setup_method(self):
        self.hc = _import_hardcover()

    def test_pre_escaped_input_doubles_escapes(self):
        # If the caller passes already-escaped text, we escape it again —
        # backslash-first ordering means r"\*" becomes r"\\\*"
        out = self.hc.escape_markdown(r"\*")
        assert out == r"\\\*"

    def test_all_special_chars_in_one_string(self):
        # Each special char gets exactly one leading backslash
        specials = '`*_{}[]()#+!|<>'
        out = self.hc.escape_markdown(specials)
        # No raw special chars remain (all preceded by \)
        for ch in specials:
            # Must always be preceded by backslash
            idx = out.find(ch)
            while idx != -1:
                assert idx > 0 and out[idx - 1] == "\\", (
                    f"char {ch!r} at {idx} not escaped: {out!r}"
                )
                idx = out.find(ch, idx + 1)

    def test_unicode_passes_through(self):
        # Emoji and accented chars aren't in the special set
        out = self.hc.escape_markdown("café 📚")
        assert "café" in out
        assert "📚" in out

    def test_newlines_pass_through(self):
        # Newlines aren't escaped (would break legitimate markdown
        # paragraphs in annotations)
        out = self.hc.escape_markdown("line1\nline2")
        assert "\n" in out

    def test_lone_backslash_doubled(self):
        out = self.hc.escape_markdown("\\")
        assert out == "\\\\"

    def test_long_input_does_not_blow_up_length_more_than_2x(self):
        # Worst case: every char is special → output length 2N
        out = self.hc.escape_markdown("*" * 1000)
        assert len(out) == 2000

    def test_non_string_input_raises_attribute_error(self):
        # Documented contract: callers must pass str (or None/empty).
        # Passing int raises AttributeError on .replace() — pin this so
        # we notice if it changes silently.
        with pytest.raises(AttributeError):
            self.hc.escape_markdown(123)

    def test_zero_is_falsy_returns_zero(self):
        # `if not text` short-circuits for 0 (falsy) — pinned behavior
        assert self.hc.escape_markdown(0) == 0


class TestHardcoverClientConstructionEdgeCases:
    def setup_method(self):
        self.hc = _import_hardcover()

    def test_whitespace_only_token_accepted_currently(self):
        # Documented quirk: `if not token` is False for non-empty
        # whitespace, so "   " constructs successfully. The 401 path in
        # execute() will eventually reject it. If we tighten the check,
        # this test should be inverted to pytest.raises.
        client = self.hc.HardcoverClient(token="   ")
        assert "Bearer    " in client.headers["Authorization"]

    def test_int_zero_token_rejected(self):
        # `if not token` is True for 0 → falsy → rejected
        with pytest.raises(self.hc.MissingHardcoverToken):
            self.hc.HardcoverClient(token=0)  # type: ignore[arg-type]

    def test_bool_false_token_rejected(self):
        # False is falsy
        with pytest.raises(self.hc.MissingHardcoverToken):
            self.hc.HardcoverClient(token=False)  # type: ignore[arg-type]

    def test_constructor_does_not_call_network(self):
        # Privacy is lazy — see the comment in the class. Construction
        # must not block on a network call (the worker uses this in
        # __init__ paths).
        client = self.hc.HardcoverClient(token="x")
        assert client._privacy is None  # not yet fetched


# ---------------------------------------------------------------------------
# Static invariants
# ---------------------------------------------------------------------------

class TestNetworkSafety:
    def test_no_verify_false_in_requests_calls(self):
        # TLS verification must never be disabled
        src = _read(HC_PATH)
        assert "verify=False" not in src
        assert "verify = False" not in src

    def test_requests_call_has_timeout(self):
        # Every requests.post/get must have a timeout or the bad-network
        # case hangs the worker forever
        src = _read(HC_PATH)
        # Find every requests.<verb>( call and check timeout=
        for m in re.finditer(r"requests\.(post|get|put|delete)\(", src):
            # Pull the next ~400 chars (call arguments)
            chunk = src[m.start():m.start() + 600]
            assert "timeout" in chunk, (
                f"requests.{m.group(1)}(...) at offset {m.start()} has no timeout"
            )

    def test_uses_bearer_authorization_header(self):
        src = _read(HC_PATH)
        assert 'Authorization' in src
        assert 'Bearer' in src


class TestErrorHandling:
    def test_401_raises_missing_token_not_generic(self):
        src = _read(HC_PATH)
        # The execute() method must specifically map 401 to
        # MissingHardcoverToken so the scheduler can disable the per-user
        # job instead of retrying forever
        execute_fn = re.search(
            r"def execute\(self.*?\n(.*?)(?=\n    def |\nclass |\Z)",
            src,
            re.DOTALL,
        )
        assert execute_fn, "Could not locate execute() body"
        body = execute_fn.group(1)
        assert "401" in body
        assert "MissingHardcoverToken" in body

    def test_graphql_errors_are_raised(self):
        # Don't silently return data with errors[] populated
        src = _read(HC_PATH)
        execute_fn = re.search(
            r"def execute\(self.*?\n(.*?)(?=\n    def |\nclass |\Z)",
            src,
            re.DOTALL,
        )
        body = execute_fn.group(1)
        assert '"errors" in result' in body or "'errors' in result" in body
        # And the branch raises rather than returning silently
        assert "raise" in body


class TestNoSilentSwallow:
    """No `except Exception: pass` — that's how the Hardcover scheduler
    bug hid for weeks. If we add error handling, log it."""

    def test_no_bare_except_pass(self):
        src = _read(HC_PATH)
        assert not re.search(r"except\s+Exception:\s*\n\s*pass\b", src)
        assert not re.search(r"except\s*:\s*\n\s*pass\b", src)
