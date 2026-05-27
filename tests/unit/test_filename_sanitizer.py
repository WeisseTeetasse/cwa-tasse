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


class TestGetValidFilenameSharedEdgeCases:
    """Edge cases that pin observed behavior — read these tests to learn
    the precise contract before refactoring this function."""

    def test_only_dots_replaces_only_last_dot(self):
        # Documented behavior: only the LAST trailing dot is replaced
        # with '_', not all of them. "..." → ".._"
        assert get_valid_filename_shared("...") == ".._"
        assert get_valid_filename_shared("a..") == "a._"

    def test_idempotent_on_already_safe_input(self):
        once = get_valid_filename_shared("a/b:c")
        twice = get_valid_filename_shared(once)
        assert once == twice  # No further changes on second pass

    def test_newline_passes_through(self):
        # Documented quirk: newlines are NOT in the forbidden set.
        # If you need newline-stripping, do it before calling.
        out = get_valid_filename_shared("a\nb")
        assert "\n" in out

    def test_tab_passes_through(self):
        # Same as newline — tabs are not stripped
        out = get_valid_filename_shared("a\tb")
        assert "\t" in out

    def test_all_forbidden_chars_combined(self):
        # Sanity: every char in the forbidden set replaced in one go
        out = get_valid_filename_shared('a/b\\c:"d|e<f>g?h*i+j')
        # /\:"<>?*+ → _, pipe → ,
        for bad in '/\\:"<>?*+':
            assert bad not in out
        assert "|" not in out
        assert "," in out  # pipe replacement marker

    def test_chars_equals_1_truncates(self):
        out = get_valid_filename_shared("hello", chars=1)
        # 1 byte cap → 1-char ASCII
        assert len(out.encode("utf-8")) <= 1

    def test_only_zero_width_chars_raises(self):
        # After stripping, nothing left → ValueError (don't return empty)
        with pytest.raises(ValueError):
            get_valid_filename_shared("​‌‍﻿")

    def test_emoji_preserved_when_unicode_filename_off(self):
        # Default mode keeps non-ASCII — Calibre's filesystem layer
        # handles emoji on modern OSes
        assert "📚" in get_valid_filename_shared("📚 Book")

    def test_combining_accent_preserved(self):
        # 'café' (composed or with combining accent) should pass through
        assert "café" in get_valid_filename_shared("café")

    def test_just_a_forward_slash(self):
        # Pathological: input is literally one forbidden char
        assert get_valid_filename_shared("/") == "_"

    def test_unicode_transliteration_partial(self):
        # Mixed-script with unicode=True: only the non-ASCII gets
        # transliterated. ASCII stays as-is.
        out = get_valid_filename_shared("Hello Привет", unicode_filename=True)
        assert "Hello" in out
        assert out.isascii()

    def test_byte_truncation_caps_at_chars_for_multibyte(self):
        # Sanity check: a long ASCII string is capped exactly at `chars`
        out = get_valid_filename_shared("a" * 500, chars=128, replace_whitespace=False)
        assert len(out.encode("utf-8")) == 128

    def test_consecutive_regex_chars_collapse(self):
        # Documented quirk: the regex `[*+:\"<>?]+` collapses runs of
        # those chars to one `_`. But `/` is replaced earlier via plain
        # str.replace("/","_"), so `///` becomes `___` (NOT collapsed).
        # This test pins both behaviors.
        assert get_valid_filename_shared("a***b") == "a_b"   # collapsed
        assert get_valid_filename_shared("a///b") == "a___b"  # not collapsed

    def test_float_input_coerced(self):
        # Non-str inputs become str(value); 3.14 → "3.14"
        assert get_valid_filename_shared(3.14) == "3.14"

    def test_bytes_input_coerced(self):
        # bytes goes through str() which gives "b'...'" — not ideal but
        # documents current behavior so a refactor doesn't silently
        # change it
        out = get_valid_filename_shared(b"hello")
        assert "hello" in out
