# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Static checks for the security hardening cuts in this branch.

These tests don't spin up the Flask app — they read source files and verify
that the security-sensitive structure stays in place even if surrounding code
is refactored.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WEB = PROJECT_ROOT / "cps" / "web.py"
ADMIN = PROJECT_ROOT / "cps" / "admin.py"
HELPER = PROJECT_ROOT / "cps" / "helper.py"
UB = PROJECT_ROOT / "cps" / "ub.py"
KOBO_AUTH = PROJECT_ROOT / "cps" / "kobo_auth.py"
USERMGMT = PROJECT_ROOT / "cps" / "usermanagement.py"
KOSYNC = PROJECT_ROOT / "cps" / "progress_syncing" / "protocols" / "kosync.py"
RESET_TPL = PROJECT_ROOT / "cps" / "templates" / "reset_password.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestPerIPRateLimiting:
    def test_login_post_has_per_ip_limit(self):
        src = _read(WEB)
        # The /login POST handler still needs the existing username-keyed
        # limit, plus an additional per-IP bucket so an attacker can't bypass
        # it by spreading attempts across many usernames.
        login_block = re.search(
            r"@web\.route\('/login', methods=\['POST'\]\)(.*?)def login_post",
            src, re.DOTALL,
        )
        assert login_block, "Could not locate the /login POST handler"
        decorators = login_block.group(1)
        assert "key_func=get_remote_address" in decorators, (
            "/login POST is missing a per-IP rate limit decorator"
        )

    def test_kosync_auth_has_per_ip_limit(self):
        src = _read(KOSYNC)
        block = re.search(
            r"@kosync\.route\(\"/kosync/users/auth\"[^)]*\)(.*?)def auth_user",
            src, re.DOTALL,
        )
        assert block, "Could not locate kosync auth_user route"
        decorators = block.group(1)
        assert "limiter.limit" in decorators
        assert "get_remote_address" in decorators

    def test_basic_auth_has_failure_throttle(self):
        src = _read(USERMGMT)
        # The HTTP Basic auth verifier (used by OPDS) must throttle by IP.
        assert "_basic_auth_rate_limited" in src
        assert "_basic_auth_record_failure" in src
        # Both helpers must be referenced from verify_password.
        verify = re.search(r"def verify_password\([^)]*\):(.*?)\n\n\n", src, re.DOTALL)
        assert verify, "Could not locate verify_password"
        body = verify.group(1)
        assert "_basic_auth_rate_limited(" in body
        assert "_basic_auth_record_failure(" in body


class TestKoboSessionEscalation:
    def test_login_user_called_with_remember_false(self):
        src = _read(KOBO_AUTH)
        # We intentionally still call login_user(user) so downstream Kobo
        # routes can use current_user, but it must be remember=False so we
        # don't issue a long-lived remember-me cookie that could be lifted
        # alongside the auth_token.
        assert "login_user(user, remember=False)" in src
        assert "login_user(user)" not in re.sub(r"login_user\(user, remember=False\)", "", src)

    def test_revoke_helper_exists(self):
        src = _read(KOBO_AUTH)
        assert "def revoke_kobo_tokens_for_user(" in src
        # Must scope to Kobo tokens only (token_type == 1) so we don't blow
        # away other auth tokens the user may have.
        assert "RemoteAuthToken.token_type == 1" in src

    def test_password_change_handlers_revoke_kobo_tokens(self):
        web_src = _read(WEB)
        admin_src = _read(ADMIN)
        # web.py change_profile() — self password change.
        assert "revoke_kobo_tokens_for_user(current_user.id)" in web_src
        # admin.py edit-user — admin changing another user's password.
        assert "revoke_kobo_tokens_for_user(content.id)" in admin_src


class TestPasswordResetTokenFlow:
    def test_user_model_has_reset_columns(self):
        src = _read(UB)
        assert "password_reset_token = Column(String" in src
        assert "password_reset_expires = Column(DateTime" in src

    def test_migration_adds_reset_columns(self):
        src = _read(UB)
        # The migrate_user_table block must add both columns idempotently
        # (i.e. via the existing safe-migrate helper).
        assert "password_reset_token" in src
        assert "password_reset_expires" in src
        assert "ALTER TABLE user ADD column" in src  # uses the same pattern
        # Confirm both column names appear in the migration tuple. The outer
        # tuple contains nested tuples, so we slice from the marker to the
        # nearest blank-line / next statement to inspect the block.
        idx = src.find("password_reset_columns = (")
        assert idx != -1, "Could not find password_reset_columns migration block"
        block = src[idx:idx + 600]
        assert "password_reset_token" in block
        assert "password_reset_expires" in block

    def test_helper_provides_token_link_flow(self):
        src = _read(HELPER)
        assert "def generate_password_reset_link(" in src
        assert "def consume_password_reset_token(" in src
        assert "def clear_password_reset_token(" in src
        # Must use a cryptographically strong token.
        assert "secrets.token_urlsafe" in src
        # Link must be rendered as /reset-password/<token>, not a cleartext password.
        assert "reset-password/" in src

    def test_login_post_uses_token_link_not_cleartext(self):
        src = _read(WEB)
        # The forgot-password branch must call generate_password_reset_link,
        # not the legacy reset_password() that emails a fresh password.
        block = re.search(
            r"if form\.get\('forgot', \"\"\) == 'forgot':(.*?)(?:else:|flash\(generic_message)",
            src, re.DOTALL,
        )
        assert block, "Could not locate forgot-password branch"
        body = block.group(1)
        assert "generate_password_reset_link(" in body
        assert "reset_password(user.id)" not in body

    def test_reset_routes_are_present(self):
        src = _read(WEB)
        assert "@web.route('/reset-password/<token>', methods=['GET'])" in src
        assert "@web.route('/reset-password/<token>', methods=['POST'])" in src
        # The submit handler must clear the token and revoke Kobo sessions.
        assert "clear_password_reset_token(user)" in src
        assert "revoke_kobo_tokens_for_user(user.id)" in src

    def test_reset_template_exists_and_csrf_protected(self):
        src = _read(RESET_TPL)
        assert 'name="csrf_token"' in src
        assert 'name="password"' in src
        assert 'name="password_confirm"' in src
