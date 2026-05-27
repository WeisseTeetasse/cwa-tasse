# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Static invariants for Kobo authentication hardening (fork additions).

Bugs/security gaps these tests guard against:
- requires_kobo_auth used to call ``login_user(user)`` with the default
  ``remember=True``, which issued a persistent Flask-Login remember-me
  cookie alongside the request. If the auth_token was later exfiltrated,
  the persistent cookie would survive token revocation. Fix: explicit
  ``remember=False``.
- Password change paths (web.py change_profile and admin.py admin user
  edit) did not revoke Kobo tokens. A leaked password used to also leak
  Kobo sync state. Fix: revoke_kobo_tokens_for_user() called from both.
- Token deletion routes used to accept any user_id; now they require
  the requesting user to own the token (or be admin).
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
KOBO_AUTH = PROJECT_ROOT / "cps" / "kobo_auth.py"
WEB = PROJECT_ROOT / "cps" / "web.py"
ADMIN = PROJECT_ROOT / "cps" / "admin.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestRequiresKoboAuthSessionHardening:
    def test_login_user_passes_remember_false(self):
        src = _read(KOBO_AUTH)
        # Find the call inside requires_kobo_auth's inner function
        block = re.search(
            r"def requires_kobo_auth\(.*?\n(.*?)return inner",
            src,
            re.DOTALL,
        )
        assert block, "Could not locate requires_kobo_auth body"
        body = block.group(1)
        # The call must explicitly opt out of persistent cookies
        assert re.search(r"login_user\(\s*user\s*,\s*remember\s*=\s*False", body), (
            "login_user must be called with remember=False to avoid a "
            "long-lived remember-me cookie surviving token revocation"
        )

    def test_remember_false_has_explanatory_comment(self):
        # Future LLMs (you, in 6 months) will try to "clean up" remember=False
        # if there's no comment. Pin the comment.
        src = _read(KOBO_AUTH)
        block = re.search(
            r"def requires_kobo_auth\(.*?\n(.*?)return inner",
            src,
            re.DOTALL,
        )
        body = block.group(1)
        # Must mention either "remember" or "cookie" in the comments
        comment_lines = [
            line.strip()
            for line in body.split("\n")
            if line.strip().startswith("#")
        ]
        assert any(
            "remember" in c.lower() or "cookie" in c.lower() or "token" in c.lower()
            for c in comment_lines
        ), "remember=False needs an explanatory comment so it isn't 'cleaned up'"


class TestTokenRevocationHelper:
    def test_revoke_helper_exists(self):
        src = _read(KOBO_AUTH)
        assert "def revoke_kobo_tokens_for_user(" in src

    def test_revoke_helper_filters_by_token_type(self):
        # Must only delete token_type==1 (Kobo) — other token types may
        # exist (OAuth, etc.) and would be a different concern
        src = _read(KOBO_AUTH)
        block = re.search(
            r"def revoke_kobo_tokens_for_user\(.*?\n(.*?)(?=\ndef |\Z)",
            src,
            re.DOTALL,
        )
        assert block
        body = block.group(1)
        assert "token_type == 1" in body

    def test_revoke_helper_logs_count(self):
        # Audit trail: a password change should be a log line, not silent
        src = _read(KOBO_AUTH)
        block = re.search(
            r"def revoke_kobo_tokens_for_user\(.*?\n(.*?)(?=\ndef |\Z)",
            src,
            re.DOTALL,
        )
        body = block.group(1)
        assert "log.info" in body or "log.warning" in body


class TestPasswordChangeRevokesKoboTokens:
    """Both user-self-service and admin password change must revoke."""

    def test_change_profile_calls_revoke_after_password_change(self):
        src = _read(WEB)
        # We can't tell from regex exactly where in change_profile, but the
        # call must appear in the file at all
        assert "revoke_kobo_tokens_for_user(" in src

    def test_admin_user_edit_calls_revoke_on_password_change(self):
        src = _read(ADMIN)
        assert "revoke_kobo_tokens_for_user(" in src


class TestOwnershipChecksOnKoboRoutes:
    """Every user_id-parameterized route must reject other-user access
    unless the caller is admin."""

    def test_generate_auth_token_checks_ownership(self):
        src = _read(KOBO_AUTH)
        block = re.search(
            r"def generate_auth_token\(user_id\):(.*?)(?=\ndef |\Z)",
            src,
            re.DOTALL,
        )
        assert block, "Could not locate generate_auth_token"
        body = block.group(1)
        assert "current_user.id" in body
        assert "role_admin" in body
        assert "abort(403)" in body

    def test_delete_auth_token_checks_ownership(self):
        src = _read(KOBO_AUTH)
        block = re.search(
            r"def delete_auth_token\(user_id\):(.*?)(?=\ndef |\Z)",
            src,
            re.DOTALL,
        )
        body = block.group(1)
        assert "current_user.id" in body
        assert "role_admin" in body
        assert "abort(403)" in body

    def test_rename_token_checks_ownership(self):
        src = _read(KOBO_AUTH)
        block = re.search(
            r"def rename_token\(user_id, token_id\):(.*?)(?=\ndef |\Z)",
            src,
            re.DOTALL,
        )
        body = block.group(1)
        assert "current_user.id" in body
        assert "abort(403)" in body
