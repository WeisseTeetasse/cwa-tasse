# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for Kobo cover cache-busting helpers."""

from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import uuid as uuidlib

import pytest


def _load_cover_cache_module():
    module_path = Path(__file__).resolve().parents[2] / "cps" / "kobo_cover_cache.py"
    spec = importlib.util.spec_from_file_location("kobo_cover_cache", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kobo_cache = _load_cover_cache_module()


@pytest.mark.unit
class TestKoboCoverImageId:
    def test_normalize_cover_uuid_keeps_plain_uuid(self):
        value = str(uuidlib.uuid4())
        assert kobo_cache.normalize_cover_uuid(value) == value

    def test_normalize_cover_uuid_strips_numeric_suffix(self):
        base = str(uuidlib.uuid4())
        value = f"{base}-1700000000"
        assert kobo_cache.normalize_cover_uuid(value) == base

    def test_normalize_cover_uuid_ignores_non_numeric_suffix(self):
        base = str(uuidlib.uuid4())
        value = f"{base}-notanumber"
        assert kobo_cache.normalize_cover_uuid(value) == value

    def test_cover_image_id_uses_mtime_when_local_cover_exists(self, tmp_path):
        book_uuid = uuidlib.uuid4()
        cover_dir = tmp_path / "Author" / "Title"
        cover_dir.mkdir(parents=True, exist_ok=True)
        cover_file = cover_dir / "cover.jpg"
        cover_file.write_bytes(b"test")

        mtime = 1700000123
        os.utime(cover_file, (mtime, mtime))

        expected = f"{book_uuid}-{mtime}"
        assert kobo_cache.build_cover_image_id(
            str(book_uuid),
            use_google_drive=False,
            last_modified=None,
            cover_path=str(cover_file),
        ) == expected

    def test_cover_image_id_falls_back_without_cover(self, tmp_path):
        book_uuid = uuidlib.uuid4()
        cover_path = tmp_path / "Missing" / "Cover" / "cover.jpg"
        assert kobo_cache.build_cover_image_id(
            str(book_uuid),
            use_google_drive=False,
            last_modified=None,
            cover_path=str(cover_path),
        ) == str(book_uuid)

    def test_cover_image_id_uses_last_modified_on_gdrive(self):
        book_uuid = uuidlib.uuid4()
        last_modified = datetime(2026, 2, 5, 12, 30, 0, tzinfo=timezone.utc)
        expected = f"{book_uuid}-{int(last_modified.timestamp())}"
        assert kobo_cache.build_cover_image_id(
            str(book_uuid),
            use_google_drive=True,
            last_modified=last_modified,
            cover_path=None,
        ) == expected


@pytest.mark.unit
class TestKoboCoverImageIdEdgeCases:
    """Edge cases that pin observed behavior."""

    def test_normalize_uppercase_uuid_preserved_as_is(self):
        # uuid.UUID() accepts uppercase — returned unchanged
        base = str(uuidlib.uuid4()).upper()
        assert kobo_cache.normalize_cover_uuid(base) == base

    def test_normalize_hex_string_without_hyphens_passes_through(self):
        # 32-char hex (valid input to uuid.UUID()) is preserved
        base = uuidlib.uuid4().hex  # no hyphens
        # The function calls uuid.UUID() which accepts hex; returns as-is
        assert kobo_cache.normalize_cover_uuid(base) == base

    def test_normalize_uuid_with_zero_mtime_suffix(self):
        # mtime of 0 (epoch) is a valid suffix to strip
        base = str(uuidlib.uuid4())
        assert kobo_cache.normalize_cover_uuid(f"{base}-0") == base

    def test_normalize_just_digits(self):
        # No UUID, not a uuid-suffix pattern → unchanged
        assert kobo_cache.normalize_cover_uuid("12345") == "12345"

    def test_normalize_integer_returns_input_unchanged(self):
        # Defensive: int input doesn't crash (UUID() raises TypeError,
        # rsplit('-', 1) on str(int) gives single part → returned)
        assert kobo_cache.normalize_cover_uuid(123) == 123

    def test_build_with_empty_cover_path_returns_base(self):
        # Empty string is falsy → no mtime suffix
        base = str(uuidlib.uuid4())
        assert kobo_cache.build_cover_image_id(
            base, use_google_drive=False, last_modified=None, cover_path=""
        ) == base

    def test_build_with_mtime_zero_appends_zero(self, tmp_path):
        # Edge case: cover file with mtime exactly at epoch (0)
        cover = tmp_path / "c.jpg"
        cover.write_bytes(b"x")
        os.utime(cover, (0, 0))
        base = str(uuidlib.uuid4())
        result = kobo_cache.build_cover_image_id(
            base, use_google_drive=False, last_modified=None, cover_path=str(cover)
        )
        assert result == f"{base}-0"

    def test_build_gdrive_with_non_datetime_last_modified_returns_base(self):
        # Documented: only datetime instances produce a suffix in gdrive
        # mode. Strings/ints/None all fall through to base.
        base = str(uuidlib.uuid4())
        assert kobo_cache.build_cover_image_id(
            base, use_google_drive=True, last_modified="2024-01-01", cover_path=None
        ) == base
        assert kobo_cache.build_cover_image_id(
            base, use_google_drive=True, last_modified=12345, cover_path=None
        ) == base

    def test_build_gdrive_naive_datetime_uses_local_timestamp(self):
        # Naive datetime → .timestamp() uses local timezone. We just
        # check the suffix is numeric and reasonable; exact value depends
        # on the host TZ.
        base = str(uuidlib.uuid4())
        result = kobo_cache.build_cover_image_id(
            base,
            use_google_drive=True,
            last_modified=datetime(2024, 1, 1),
            cover_path=None,
        )
        suffix = result.rsplit("-", 1)[1]
        assert suffix.isdigit()
        assert 1_700_000_000 < int(suffix) < 1_800_000_000  # 2024-ish

    def test_build_with_empty_base_returns_empty_when_no_mtime(self):
        # Pathological input: empty UUID. Documents behavior.
        result = kobo_cache.build_cover_image_id(
            "", use_google_drive=False, last_modified=None, cover_path=None
        )
        assert result == ""

    def test_normalize_then_build_roundtrip(self, tmp_path):
        # Critical invariant: build → normalize must always recover the
        # base id, no matter what the suffix looks like
        base = str(uuidlib.uuid4())
        cover = tmp_path / "c.jpg"
        cover.write_bytes(b"x")
        built = kobo_cache.build_cover_image_id(
            base, use_google_drive=False, last_modified=None, cover_path=str(cover)
        )
        assert kobo_cache.normalize_cover_uuid(built) == base
