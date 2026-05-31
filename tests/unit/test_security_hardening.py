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
CWA_FUNCTIONS = PROJECT_ROOT / "cps" / "cwa_functions.py"
READ_LOG_TPL = PROJECT_ROOT / "cps" / "templates" / "cwa_read_log.html"
LOGIN_TPL = PROJECT_ROOT / "cps" / "templates" / "login.html"


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


class TestSelfServicePasswordResetRemoved:
    """Self-service ("Forgot Password?") reset was removed for security.

    Risk: generate_password_reset_link() built the emailed reset URL from
    request.host_url — the client-controlled Host / X-Forwarded-Host header —
    with no trusted-host allowlist. An attacker could trigger a victim's reset
    with a spoofed Host so the emailed link pointed at an attacker domain;
    clicking it leaked the single-use token and allowed account takeover
    (reset-link poisoning, CWE-640). The whole self-service flow was therefore
    removed; admins reset user passwords from the admin user page instead.

    These tests pin the removal so the vulnerable flow is not reintroduced
    without consciously deleting a test.
    """

    def test_reset_link_helpers_removed_from_helper(self):
        src = _read(HELPER)
        assert "def generate_password_reset_link(" not in src
        assert "def consume_password_reset_token(" not in src
        assert "def clear_password_reset_token(" not in src
        # The Host-header-derived reset URL must be gone entirely.
        assert "reset-password/" not in src

    def test_web_has_no_reset_routes(self):
        src = _read(WEB)
        assert "/reset-password/<token>" not in src
        assert "def reset_password_form(" not in src
        assert "def reset_password_submit(" not in src

    def test_login_post_does_not_issue_reset_links(self):
        src = _read(WEB)
        # No code path may turn a request Host into an emailed reset link.
        assert "generate_password_reset_link(" not in src
        # The forgot-password branch must be gone.
        assert "form.get('forgot'" not in src

    def test_login_template_has_no_forgot_button(self):
        src = _read(LOGIN_TPL)
        assert 'name="forgot"' not in src
        assert "Forgot Password?" not in src

    def test_reset_password_template_deleted(self):
        assert not RESET_TPL.exists(), (
            "reset_password.html must stay deleted; it only served the removed "
            "self-service reset flow."
        )

    def test_reset_columns_remain_for_migration_compatibility(self):
        # The DB columns are intentionally left in place — dropping them would be
        # a destructive migration on existing installs. They are inert now that
        # no route can populate or read a reset token.
        src = _read(UB)
        assert "password_reset_token = Column(String" in src
        assert "password_reset_expires = Column(DateTime" in src
        # The idempotent migration must remain so existing DBs stay valid.
        assert "password_reset_columns = (" in src


class TestKosyncBruteForceThrottle:
    """Bug: only /kosync/users/auth was rate-limited, but get_progress() and
    update_progress() also call authenticate_user() (a full password / LDAP
    check) with no @limiter and @csrf.exempt. An unauthenticated attacker could
    brute-force credentials via the progress endpoints, bypassing the
    auth-endpoint limit and the OPDS in-memory throttle. Fix: authenticate_user()
    now enforces the shared per-IP failure throttle, covering every kosync
    endpoint that authenticates.
    """

    def test_authenticate_user_enforces_ip_throttle(self):
        src = _read(KOSYNC)
        fn = re.search(r"def authenticate_user\(.*?\):(.*?)\ndef ", src, re.DOTALL)
        assert fn, "Could not locate authenticate_user"
        body = fn.group(1)
        # Must consult the shared throttle and record failures on the bad paths.
        assert "_basic_auth_rate_limited(" in body
        assert "_basic_auth_record_failure(" in body

    def test_progress_endpoints_route_through_authenticate_user(self):
        # The throttle only protects the progress endpoints if they actually
        # authenticate via authenticate_user(); auth_user + get_progress +
        # update_progress == 3 call sites.
        src = _read(KOSYNC)
        assert src.count("user = authenticate_user()") >= 3


class TestLogRoutesRequireAuth:
    """Bug: /cwa-logs/download/<f> and /cwa-logs/read/<f> had no auth decorator,
    so anyone on the internet could download/read application logs (client IPs,
    usernames, attempted-login usernames, Kobo device names). read_log also
    rendered log content through Jinja '| safe', turning log injection into
    stored XSS in the viewer's (often admin's) browser. Fix: both routes require
    admin; the read template autoescapes.
    """

    def test_log_routes_require_admin(self):
        src = _read(CWA_FUNCTIONS)
        for route in ("/cwa-logs/download/<log_filename>", "/cwa-logs/read/<log_filename>"):
            block = re.search(
                re.escape("@cwa_logs.route('" + route + "')") + r"(.*?)\ndef ",
                src, re.DOTALL,
            )
            assert block, f"Could not locate route {route}"
            decorators = block.group(1)
            assert "@admin_required" in decorators, f"{route} is missing @admin_required"
            assert "@login_required_if_no_ano" in decorators, (
                f"{route} is missing @login_required_if_no_ano"
            )

    def test_read_log_template_autoescapes(self):
        src = _read(READ_LOG_TPL)
        # Attacker-influenced log content must be autoescaped — no '| safe'.
        assert "| safe" not in src
        assert "log | replace" not in src
