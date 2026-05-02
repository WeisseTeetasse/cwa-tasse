# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for CWA update notification version comparison."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_render_template_module(monkeypatch):
    root = Path(__file__).resolve().parents[2]

    flask = types.ModuleType("flask")
    flask.render_template = lambda *args, **kwargs: ""
    flask.g = types.SimpleNamespace()
    flask.abort = lambda *args, **kwargs: None
    flask.request = types.SimpleNamespace(headers={})
    flask.flash = lambda *args, **kwargs: None
    flask.current_app = types.SimpleNamespace(view_functions={})
    monkeypatch.setitem(sys.modules, "flask", flask)

    flask_babel = types.ModuleType("flask_babel")
    flask_babel.gettext = lambda value, **kwargs: value
    flask_babel.get_locale = lambda: "en"
    monkeypatch.setitem(sys.modules, "flask_babel", flask_babel)

    monkeypatch.setitem(sys.modules, "polib", types.ModuleType("polib"))

    werkzeug_local = types.ModuleType("werkzeug.local")
    werkzeug_local.LocalProxy = object
    monkeypatch.setitem(sys.modules, "werkzeug.local", werkzeug_local)

    sqlalchemy_expression = types.ModuleType("sqlalchemy.sql.expression")
    sqlalchemy_expression.or_ = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "sqlalchemy.sql.expression", sqlalchemy_expression)

    cps = types.ModuleType("cps")
    cps.__path__ = [str(root / "cps")]
    cps.config = types.SimpleNamespace()
    cps.constants = types.SimpleNamespace()
    cps.ub = types.SimpleNamespace()
    cps.logger = types.SimpleNamespace(create=lambda: types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "cps", cps)

    cw_login = types.ModuleType("cps.cw_login")
    cw_login.current_user = types.SimpleNamespace(
        is_anonymous=True,
        role_admin=lambda: False,
        role_edit=lambda: False,
    )
    monkeypatch.setitem(sys.modules, "cps.cw_login", cw_login)

    ub = types.ModuleType("cps.ub")
    ub.User = type("User", (), {})
    ub.session = types.SimpleNamespace(query=lambda *args, **kwargs: types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "cps.ub", ub)

    cwa_db = types.ModuleType("cwa_db")
    cwa_db.CWA_DB = lambda: types.SimpleNamespace(cwa_settings={"cwa_update_notifications": False})
    monkeypatch.setitem(sys.modules, "cwa_db", cwa_db)

    spec = importlib.util.spec_from_file_location(
        "cps.render_template",
        root / "cps" / "render_template.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "cps.render_template", module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_fork_build_does_not_trigger_update_when_base_matches_stable(monkeypatch):
    render_template = _load_render_template_module(monkeypatch)

    update_available, current, newest = render_template._cwa_update_available_for_versions(
        "main-1d8e4ffadb52e23d5078b23db8359a6f6b948821",
        "v4.0.6",
        "v4.0.6",
    )

    assert update_available is False
    assert current == "main-1d8e4ffadb52e23d5078b23db8359a6f6b948821"
    assert newest == "v4.0.6"


@pytest.mark.unit
def test_fork_build_triggers_update_when_upstream_base_is_old(monkeypatch):
    render_template = _load_render_template_module(monkeypatch)

    update_available, current, newest = render_template._cwa_update_available_for_versions(
        "main-1d8e4ffadb52e23d5078b23db8359a6f6b948821",
        "v4.0.5",
        "v4.0.6",
    )

    assert update_available is True
    assert current == "main-1d8e4ffadb52e23d5078b23db8359a6f6b948821"
    assert newest == "v4.0.6"
