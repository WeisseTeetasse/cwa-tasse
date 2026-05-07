# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared-secret authentication for cwa-internal endpoints.

The web process and helper scripts (e.g. ingest_processor.py) call internal
endpoints over loopback HTTP. Earlier versions guarded those endpoints with
``request.headers.get('X-Forwarded-For') == '127.0.0.1'``, which is trivially
spoofable by any external attacker. This module replaces that with a random
token written once to the config directory and required on every internal call.
"""

import hmac
import os
import secrets
from functools import wraps

from flask import abort, request

from . import logger
from .constants import CONFIG_DIR

INTERNAL_TOKEN_HEADER = "X-CWA-Internal-Token"
_TOKEN_FILENAME = ".cwa_internal_token"

log = logger.create()


def _token_path():
    return os.path.join(CONFIG_DIR, _TOKEN_FILENAME)


def get_internal_token():
    """Return the shared internal-API token, creating it on first use.

    The token lives in the config directory so that helper scripts running in
    the same container can read it. File mode is 0600 to keep it out of reach
    of other local users on multi-tenant hosts.
    """
    path = _token_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            token = fh.read().strip()
            if token:
                return token
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.error("Failed to read internal token at %s: %s", path, exc)

    token = secrets.token_urlsafe(32)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Write atomically so a concurrent reader never sees an empty file.
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(token)
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, path)
    except OSError as exc:
        log.error("Failed to persist internal token at %s: %s", path, exc)
    return token


def get_internal_api_headers():
    """Return the request headers required to call cwa-internal endpoints."""
    return {INTERNAL_TOKEN_HEADER: get_internal_token()}


def requires_internal_token(func):
    """Reject callers that do not present the shared internal token."""

    @wraps(func)
    def decorated(*args, **kwargs):
        provided = request.headers.get(INTERNAL_TOKEN_HEADER, "")
        expected = get_internal_token()
        if not provided or not hmac.compare_digest(provided, expected):
            log.warning(
                "Rejected cwa-internal call to %s from %s (missing or invalid token)",
                request.path,
                request.remote_addr,
            )
            abort(403)
        return func(*args, **kwargs)

    return decorated
