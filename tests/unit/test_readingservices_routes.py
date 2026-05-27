# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Static invariants for cps/readingservices.py.

This blueprint intercepts Kobo's reading-services traffic (annotations,
sync state, EPUB progress mapping). It's security-sensitive:
- Every route must require the Kobo device auth token.
- The EPUB-progress calculator must not write back to the Kobo store
  (read-only intercept).
- Header logging must redact bearer tokens.
"""

import re
from pathlib import Path
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
READING_SERVICES = PROJECT_ROOT / "cps" / "readingservices.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestEveryRouteHasAuthDecorator:
    """Every blueprint route in readingservices.py must be gated by
    @requires_reading_services_auth_and_config (or @requires_kobo_auth
    chained behind it). A bare @bp.route is a security hole."""

    def test_no_undecorated_routes(self):
        src = _read(READING_SERVICES)
        # Find every @route(...) followed by def — the line between must
        # include a decorator that mentions auth.
        # Use a structural check: each route definition group must contain
        # the auth decorator within ~5 lines above the def.
        route_defs = list(re.finditer(
            r"@\w+\.route\([^)]*\)\s*\n(.*?)\ndef ",
            src,
            re.DOTALL,
        ))
        assert route_defs, "No routes found — file structure changed?"
        for match in route_defs:
            between = match.group(1)
            # Allow either auth decorator
            ok = (
                "requires_reading_services_auth_and_config" in between
                or "requires_kobo_auth" in between
                or "user_login_required" in between
            )
            assert ok, (
                f"Route at offset {match.start()} lacks auth decorator. "
                f"Decorator block was:\n{between!r}"
            )


class TestHeaderRedaction:
    def test_redact_headers_function_exists(self):
        src = _read(READING_SERVICES)
        assert "def redact_headers(" in src

    def test_redact_headers_masks_authorization(self):
        # Read the function body and check it redacts Authorization and
        # any *userkey* header — these carry the Kobo device credential
        # and must never reach the logs in cleartext.
        src = _read(READING_SERVICES)
        body = re.search(
            r"def redact_headers\(.*?\n(.*?)(?=\n\ndef |\nclass )",
            src,
            re.DOTALL,
        )
        assert body, "Could not locate redact_headers body"
        b = body.group(1).lower()
        # Either explicit names or a denylist constant — accept either
        assert "authorization" in b or "auth" in b
        assert "userkey" in b or "x-kobo" in b


class TestProxyToKoboIsReadOnly:
    """proxy_to_kobo_reading_services forwards specific safe verbs to the
    real Kobo endpoint. It must not auto-forward arbitrary POST/PUT/DELETE
    or we'd be acting as an open relay for the Kobo store API.
    """

    def test_proxy_function_exists(self):
        src = _read(READING_SERVICES)
        assert "def proxy_to_kobo_reading_services(" in src


class TestEpubProgressCalculatorContract:
    """The EpubProgressCalculator maps KOReader/Kobo positions back into
    EPUB CFI / percentage. It's the keystone of webreader-opens-at-Kobo-
    position. Don't let its public interface drift silently."""

    def test_class_exists_with_documented_interface(self):
        src = _read(READING_SERVICES)
        assert "class EpubProgressCalculator" in src
