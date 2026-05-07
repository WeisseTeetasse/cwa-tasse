# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Static checks for the cwa-internal token gate.

The full Flask app is too heavy to instantiate in unit tests, so we exercise
the new ``internal_auth`` module by reading its source. We also confirm that
every ``/cwa-internal/*`` route in :mod:`cps.cwa_functions` is decorated with
``@requires_internal_token`` and that no caller still relies on the old,
spoofable ``X-Forwarded-For: 127.0.0.1`` header.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CWA_FUNCTIONS = PROJECT_ROOT / "cps" / "cwa_functions.py"
INTERNAL_AUTH = PROJECT_ROOT / "cps" / "internal_auth.py"
EDITBOOKS = PROJECT_ROOT / "cps" / "editbooks.py"
INGEST_PROCESSOR = PROJECT_ROOT / "scripts" / "ingest_processor.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestInternalAuthModule:
    def test_module_exposes_required_symbols(self):
        src = _read(INTERNAL_AUTH)
        assert "INTERNAL_TOKEN_HEADER" in src
        assert "def get_internal_token" in src
        assert "def get_internal_api_headers" in src
        assert "def requires_internal_token" in src

    def test_uses_constant_time_comparison(self):
        # Token comparison must use hmac.compare_digest, not ==, so that we
        # don't leak information through timing.
        src = _read(INTERNAL_AUTH)
        assert "hmac.compare_digest" in src

    def test_token_uses_secrets_module(self):
        src = _read(INTERNAL_AUTH)
        assert "secrets.token_urlsafe" in src

    def test_token_file_uses_dot_prefix(self):
        # The token is a sensitive secret. Storing it in a dotfile keeps it
        # out of casual `ls` listings inside /config.
        src = _read(INTERNAL_AUTH)
        assert ".cwa_internal_token" in src


class TestInternalRoutesAreGuarded:
    """Every /cwa-internal/* route must require the shared token."""

    INTERNAL_ROUTE_RE = re.compile(
        r"@cwa_internal\.route\(['\"]/cwa-internal/[^'\"]+['\"][^)]*\)\s*"
        r"(@\w+\s*)*"  # any number of decorators after the route
    )

    def test_every_internal_route_uses_token_decorator(self):
        src = _read(CWA_FUNCTIONS)
        # Pull the chunk between each @cwa_internal.route(...) and the next
        # `def ` to make sure @requires_internal_token sits in the decorator
        # stack.
        positions = [m.start() for m in re.finditer(r"@cwa_internal\.route\(", src)]
        assert positions, "Expected at least one /cwa-internal/* route"
        for start in positions:
            chunk = src[start:start + 600]
            def_idx = chunk.find("def ")
            assert def_idx != -1, "Could not locate function start after @cwa_internal.route"
            decorator_block = chunk[:def_idx]
            assert "@requires_internal_token" in decorator_block, (
                "A /cwa-internal/* route is missing @requires_internal_token:\n"
                + decorator_block
            )

    def test_no_legacy_x_forwarded_for_check(self):
        # The old, spoofable check has been removed.
        src = _read(CWA_FUNCTIONS)
        assert "request.headers.get('X-Forwarded-For'" not in src
        assert 'request.headers.get("X-Forwarded-For"' not in src


class TestCallersSendInternalToken:
    """Outbound callers must attach the internal token header."""

    def test_editbooks_no_longer_spoofs_x_forwarded_for(self):
        src = _read(EDITBOOKS)
        assert '"X-Forwarded-For": "127.0.0.1"' not in src
        assert "get_internal_api_headers" in src

    def test_cwa_functions_outbound_calls_use_token(self):
        src = _read(CWA_FUNCTIONS)
        # Both schedulers (convert library, epub fixer) post to the internal
        # endpoint with our token-injecting helper. The first occurrence of
        # the endpoint string is the route definition; the *outbound* caller
        # uses `helper.get_internal_api_url("...")`, so look for that form.
        for endpoint in (
            "/cwa-internal/schedule-convert-library",
            "/cwa-internal/schedule-epub-fixer",
        ):
            marker = f'helper.get_internal_api_url("{endpoint}")'
            idx = src.find(marker)
            assert idx != -1, f"Expected outbound caller for {endpoint}"
            window = src[idx:idx + 600]
            assert "headers=get_internal_api_headers()" in window, (
                f"Outbound caller for {endpoint} is not sending the internal token"
            )

    def test_ingest_processor_reads_token_from_disk(self):
        src = _read(INGEST_PROCESSOR)
        assert "X-CWA-Internal-Token" in src
        assert ".cwa_internal_token" in src
        # The legacy spoofing header should no longer appear.
        assert '"X-Forwarded-For": "127.0.0.1"' not in src
