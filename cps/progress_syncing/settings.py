# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Helpers for KOReader sync feature flags."""

import sys

# Access CWA_DB from scripts path (consistent with existing patterns)
sys.path.insert(1, '/app/calibre-web-automated/scripts/')


def is_koreader_sync_enabled() -> bool:
    """Return True if KOReader sync is enabled in CWA settings.

    Catches BaseException (not just Exception) because CWA_DB.connect_to_db
    calls ``sys.exit(0)`` on connection failure — that's a SystemExit
    which doesn't inherit from Exception. Without this catch, a missing
    or unreadable /config/app.db silently aborts the calling script
    (e.g. scripts/generate_book_checksums.py) with no error message.
    """
    try:
        from cwa_db import CWA_DB
        settings = CWA_DB().cwa_settings
        return bool(settings.get('koreader_sync_enabled', 0))
    except BaseException:
        # Fail closed to avoid unexpected DB writes when setting is missing.
        # BaseException (not Exception) catches the sys.exit(0) raised by
        # cwa_db.connect_to_db when /config/app.db is unavailable.
        return False
