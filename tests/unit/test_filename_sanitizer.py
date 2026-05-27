# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Behavioral tests for cps.utils.filename_sanitizer.

This is a pure helper (no Flask, no DB) shared by the upload path and the
ingest worker. If its output changes silently, filenames on disk diverge
from what Calibre expects and books "disappear" from the library view.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_module():
    """Load cps.utils.filename_sanitizer in isolation so the test does not
    trigger cps/__init__.py (which pulls in heavyweight optional deps).
    """
    path = PROJECT_ROOT / "cps" / "utils" / "filename_sanitizer.py"
    spec = importlib.util.spec_from_file_location("_filename_sanitizer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_m = _load_module()
get_valid_filename_shared = _m.get_valid_filename_shared
strip_whitespaces = _m.strip_whitespaces


class TestStripWhitespaces:
    def test_strips_ascii_whitespace_both_ends(self):
        assert strip_whitespaces("  hello  ") == "hello"

    def test_strips_zero_width_chars(self):
        # U+200B zero-width space, U+FEFF BOM
        assert strip_whitespaces("​hello﻿") == "hello"

    def test_preserves_inner_whitespace(self):
        assert strip_whitespaces("  a b  c  ") == "a b  c"

    def test_empty_string(self):
        assert strip_whitespaces("") == ""


class TestGetValidFilenameShared:
    def test_basic_filename_passthrough(self):
        assert get_valid_filename_shared("My Book") == "My Book"

    def test_trailing_dot_replaced_with_underscore(self):
        # Windows would treat "name." as "name"; we make it explicit
        assert get_valid_filename_shared("My Book.").endswith("_")

    def test_forward_slash_replaced(self):
        assert "/" not in get_valid_filename_shared("a/b/c")

    def test_colon_replaced(self):
        assert ":" not in get_valid_filename_shared("Author: Title")

    def test_null_byte_at_end_stripped(self):
        # `.strip('\0')` is end-strip only — that's the documented behavior
        result = get_valid_filename_shared("badname\0")
        assert not result.endswith("\0")

    def test_forbidden_windows_chars_replaced_with_underscore(self):
        result = get_valid_filename_shared('a*b+c:d"e/f<g>h?i')
        # All of *+:"/<>? should become _
        for bad in '*+:"/<>?':
            assert bad not in result

    def test_pipe_replaced_with_comma(self):
        # Documented quirk: pipe → comma (not underscore) for Calibre compat
        assert "|" not in get_valid_filename_shared("a|b|c")
        assert "," in get_valid_filename_shared("a|b|c")

    def test_truncates_to_max_chars(self):
        long = "a" * 500
        assert len(get_valid_filename_shared(long, chars=128).encode("utf-8")) <= 128

    def test_utf8_safe_truncation_does_not_split_multibyte(self):
        # Truncation at byte 128 in middle of multi-byte char must not raise
        # or produce invalid UTF-8. The 'errors=ignore' path drops the partial.
        # Each ✓ is 3 bytes in UTF-8, so 50 of them = 150 bytes
        long = "✓" * 50
        result = get_valid_filename_shared(long, chars=128)
        # Must be valid UTF-8 (won't raise on encode)
        result.encode("utf-8")
        # And not exceed the byte budget
        assert len(result.encode("utf-8")) <= 128

    def test_empty_after_sanitization_raises(self):
        # If the input reduces to empty after stripping, raise ValueError
        # rather than returning "" which would be a silent corruption.
        with pytest.raises(ValueError):
            get_valid_filename_shared("   ")

    def test_none_input_coerced(self):
        # Defensive: None → "" → raises (instead of AttributeError)
        with pytest.raises(ValueError):
            get_valid_filename_shared(None)  # type: ignore[arg-type]

    def test_int_input_coerced_to_string(self):
        # Non-str inputs become str(value)
        assert get_valid_filename_shared(12345) == "12345"

    def test_unicode_filename_transliterates_when_enabled(self):
        unidecode = pytest.importorskip("unidecode")
        # Cyrillic should transliterate to ASCII
        out = get_valid_filename_shared("Привет", unicode_filename=True)
        assert out.isascii()

    def test_unicode_filename_preserves_when_disabled(self):
        # Default: keep unicode (Calibre handles it)
        out = get_valid_filename_shared("Привет", unicode_filename=False)
        assert "Привет" in out

    def test_replace_whitespace_false_keeps_special_chars(self):
        # When the caller knows what they're doing (e.g. building a glob),
        # they can skip the *+:"/<>? replacement
        out = get_valid_filename_shared("a*b", replace_whitespace=False)
        assert "*" in out
