#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""This module is used to control authentication/authorization of Kobo sync requests.
This module also includes research notes into the auth protocol used by Kobo devices.

Log-in:
When first booting a Kobo device the user must sign into a Kobo (or affiliate) account.
Upon successful sign-in, the user is redirected to
    https://auth.kobobooks.com/CrossDomainSignIn?id=<some id>
which serves the following response:
    <script type='text/javascript'>
        location.href='kobo://UserAuthenticated?userId=<redacted>&userKey<redacted>&email=<redacted>&returnUrl=https%3a%2f%2fwww.kobo.com';
    </script>
And triggers the insertion of a userKey into the device's User table.

Together, the device's DeviceId and UserKey act as an *irrevocable* authentication
token to most (if not all) Kobo APIs. In fact, in most cases only the UserKey is
required to authorize the API call.

Changing Kobo password *does not* invalidate user keys! This is apparently a known
issue for a few years now https://www.mobileread.com/forums/showpost.php?p=3476851&postcount=13
(although this poster hypothesised that Kobo could blacklist a DeviceId, many endpoints
will still grant access given the userkey.)

Official Kobo Store Api authorization:
* For most of the endpoints we care about (sync, metadata, tags, etc), the userKey is
passed in the x-kobo-userkey header, and is sufficient to authorize the API call.
* Some endpoints (e.g: AnnotationService) instead make use of Bearer tokens pass through
an authorization header. To get a BearerToken, the device makes a POST request to the
v1/auth/device endpoint with the secret UserKey and the device's DeviceId.
* The book download endpoint passes an auth token as a URL param instead of a header.

Our implementation:
We pretty much ignore all of the above. To authenticate the user, we generate a random
and unique token that they append to the CalibreWeb Url when setting up the api_store
setting on the device.
Thus, every request from the device to the api_store will hit CalibreWeb with the
auth_token in the url (e.g: https://mylibrary.com/<auth_token>/v1/library/sync).
In addition, once authenticated we also set the login cookie on the response that will
be sent back for the duration of the session to authorize subsequent API calls (in
particular calls to non-Kobo specific endpoints such as the CalibreWeb book download).
"""

from binascii import hexlify
from datetime import datetime
from os import urandom
from functools import wraps

from flask import g, Blueprint, abort, request, jsonify
from .cw_login import login_user, current_user
from flask_babel import gettext as _
from flask_limiter import RateLimitExceeded

from . import logger, config, calibre_db, db, helper, ub, lm, limiter
from .render_template import render_title_template
from .usermanagement import user_login_required


log = logger.create()

kobo_auth = Blueprint("kobo_auth", __name__, url_prefix="/kobo_auth")


@kobo_auth.route("/generate_auth_token/<int:user_id>")
@user_login_required
def generate_auth_token(user_id):
    if user_id != current_user.id and not current_user.role_admin():
        return abort(403)

    warning = False
    host_list = request.host.rsplit(':')
    if len(host_list) == 1:
        host = ':'.join(host_list)
    else:
        host = ':'.join(host_list[0:-1])
    if host.startswith('127.') or host.lower() == 'localhost' or host.startswith('[::ffff:7f') or host == "[::1]":
        warning = _('Please access Calibre-Web Automated from non localhost to get valid api_endpoint for kobo device')

    if request.args.get("create") == "1":
        auth_token = ub.RemoteAuthToken()
        auth_token.user_id = user_id
        auth_token.expiration = datetime.max
        auth_token.auth_token = (hexlify(urandom(16))).decode("utf-8")
        auth_token.token_type = 1
        ub.session.add(auth_token)
        ub.session.flush()
        auth_token.token_name = _("Kobo Device %(num)s", num=auth_token.id)
        ub.session_commit()

    books = calibre_db.session.query(db.Books).join(db.Data).all()

    for book in books:
        formats = [data.format for data in book.data]
        if 'KEPUB' not in formats and config.config_kepubifypath and 'EPUB' in formats:
            helper.convert_book_format(book.id, config.config_calibre_dir, 'EPUB', 'KEPUB', current_user.name)

    tokens = get_kobo_tokens_for_user(user_id)

    return render_title_template(
        "generate_kobo_auth_url.html",
        title=_("Kobo Setup"),
        tokens=tokens,
        user_id=user_id,
        warning=warning
    )


@kobo_auth.route("/deleteauthtoken/<int:user_id>", methods=["POST"])
@user_login_required
def delete_auth_token(user_id):
    if user_id != current_user.id and not current_user.role_admin():
        return abort(403)

    token_id = request.form.get("token_id", type=int)
    token_query = ub.session.query(ub.RemoteAuthToken).filter(
        ub.RemoteAuthToken.user_id == user_id,
        ub.RemoteAuthToken.token_type == 1
    )
    if token_id:
        token_query = token_query.filter(ub.RemoteAuthToken.id == token_id)
        ub.session.query(ub.KoboSyncedBooks).filter(
            ub.KoboSyncedBooks.user_id == user_id,
            ub.KoboSyncedBooks.remote_auth_token_id == token_id
        ).delete()
    else:
        ub.session.query(ub.KoboSyncedBooks).filter(
            ub.KoboSyncedBooks.user_id == user_id
        ).delete()
    token_query.delete()

    return ub.session_commit()


@kobo_auth.route("/fullsync/<int:user_id>/<int:token_id>", methods=["POST"])
@user_login_required
def full_sync_token(user_id, token_id):
    if user_id != current_user.id and not current_user.role_admin():
        return abort(403)

    token = ub.session.query(ub.RemoteAuthToken).filter(
        ub.RemoteAuthToken.user_id == user_id,
        ub.RemoteAuthToken.id == token_id,
        ub.RemoteAuthToken.token_type == 1
    ).first()
    if not token:
        return abort(404)

    count = ub.session.query(ub.KoboSyncedBooks).filter(
        ub.KoboSyncedBooks.user_id == user_id,
        ub.KoboSyncedBooks.remote_auth_token_id == token_id
    ).delete()
    ub.session_commit()
    return jsonify({"type": "success", "message": _("{} sync entries deleted").format(count)})


@kobo_auth.route("/rename/<int:user_id>/<int:token_id>", methods=["POST"])
@user_login_required
def rename_token(user_id, token_id):
    if user_id != current_user.id and not current_user.role_admin():
        return abort(403)

    token = ub.session.query(ub.RemoteAuthToken).filter(
        ub.RemoteAuthToken.user_id == user_id,
        ub.RemoteAuthToken.id == token_id,
        ub.RemoteAuthToken.token_type == 1
    ).first()
    if not token:
        return abort(404)

    token_name = (request.form.get("token_name") or "").strip()
    if not token_name:
        token_name = _("Kobo Device %(num)s", num=token.id)
    token.token_name = token_name[:80]
    ub.session_commit()
    return jsonify({"type": "success", "token_name": token.token_name})


def get_kobo_tokens_for_user(user_id):
    token_rows = ub.session.query(ub.RemoteAuthToken).filter(
        ub.RemoteAuthToken.user_id == user_id,
        ub.RemoteAuthToken.token_type == 1
    ).order_by(ub.RemoteAuthToken.id).all()
    for token in token_rows:
        token.synced_books_count = ub.session.query(ub.KoboSyncedBooks).filter(
            ub.KoboSyncedBooks.user_id == user_id,
            ub.KoboSyncedBooks.remote_auth_token_id == token.id
        ).count()
    return token_rows


def disable_failed_auth_redirect_for_blueprint(bp):
    lm.blueprint_login_views[bp.name] = None


def get_auth_token():
    if "auth_token" in g:
        return g.get("auth_token")
    else:
        return None


def get_auth_token_id():
    return g.get("auth_token_id")


def get_auth_token_name():
    return g.get("auth_token_name") or _("Unknown Kobo Device")


def register_url_value_preprocessor(kobo):
    @kobo.url_value_preprocessor
    # pylint: disable=unused-variable
    def pop_auth_token(__, values):
        g.auth_token = values.pop("auth_token")


def requires_kobo_auth(f):
    @wraps(f)
    def inner(*args, **kwargs):
        auth_token = get_auth_token()
        if auth_token is not None:
            try:
                limiter.check()
            except RateLimitExceeded:
                return abort(429)
            except (ConnectionError, Exception) as e:
                log.error("Connection error to limiter backend: %s", e)
                return abort(429)
            auth_token_row = (
                ub.session.query(ub.RemoteAuthToken)
                .filter(ub.RemoteAuthToken.auth_token == auth_token)
                .filter(ub.RemoteAuthToken.token_type == 1)
                .first()
            )
            user = auth_token_row.user if auth_token_row else None
            if user is not None:
                auth_token_row.last_used = datetime.now()
                ub.session_commit()
                g.auth_token_id = auth_token_row.id
                g.auth_token_name = auth_token_row.token_name or _("Kobo Device %(num)s", num=auth_token_row.id)
                log.info(
                    "Kobo request from device '%s' (token %s): %s %s",
                    g.auth_token_name,
                    auth_token_row.id,
                    request.method,
                    request.path,
                )
                # Authenticate the user for this request only: pass remember=False
                # so we don't issue a long-lived Flask-Login remember-me cookie
                # that could be exfiltrated alongside (or after) the auth_token
                # to gain a full browser session. The transient Flask session
                # cookie is still set, but the device-bound auth_token is the
                # actual long-lived credential.
                login_user(user, remember=False)
                [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]
                return f(*args, **kwargs)
        log.debug("Received Kobo request without a recognizable auth token.")
        return abort(401)
    return inner


def revoke_kobo_tokens_for_user(user_id):
    """Delete all Kobo device auth tokens for the given user.

    Called after a password change so that previously paired devices have to
    re-authenticate. Returns the number of tokens removed.
    """
    try:
        deleted = (
            ub.session.query(ub.RemoteAuthToken)
            .filter(ub.RemoteAuthToken.user_id == user_id)
            .filter(ub.RemoteAuthToken.token_type == 1)
            .delete(synchronize_session=False)
        )
        ub.session_commit()
        if deleted:
            log.info("Revoked %d Kobo auth token(s) for user_id=%s after password change", deleted, user_id)
        return deleted
    except Exception as e:
        log.warning("Failed to revoke Kobo auth tokens for user_id=%s: %s", user_id, e)
        try:
            ub.session.rollback()
        except Exception:
            pass
        return 0
