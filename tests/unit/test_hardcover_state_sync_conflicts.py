# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


class _FakeLoggerFactory:
    @staticmethod
    def create():
        class _Log:
            def debug(self, *args, **kwargs):
                pass

            def info(self, *args, **kwargs):
                pass

            def warning(self, *args, **kwargs):
                pass

            def error(self, *args, **kwargs):
                pass

        return _Log()


def _load_state_sync_module():
    root = Path(__file__).resolve().parents[2]
    previous = {name: sys.modules.get(name) for name in (
        "cps",
        "cps.hardcover_state_sync",
        "cps.services",
        "cps.services.hardcover",
    )}
    fake_cps = types.ModuleType("cps")
    fake_cps.__path__ = [str(root / "cps")]
    fake_cps.calibre_db = types.SimpleNamespace()
    fake_cps.db = types.SimpleNamespace()
    fake_cps.ub = types.SimpleNamespace()
    fake_cps.logger = _FakeLoggerFactory()
    fake_services = types.ModuleType("cps.services")
    fake_hardcover = types.SimpleNamespace(
        STATUS_WANT_TO_READ=1,
        STATUS_READING=2,
        STATUS_READ=3,
        STATUS_DID_NOT_FINISH=5,
        MissingHardcoverToken=Exception,
    )
    sys.modules["cps"] = fake_cps
    sys.modules["cps.services"] = fake_services
    sys.modules["cps.services.hardcover"] = fake_hardcover
    try:
        spec = importlib.util.spec_from_file_location(
            "cps.hardcover_state_sync",
            root / "cps" / "hardcover_state_sync.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["cps.hardcover_state_sync"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


state_sync = _load_state_sync_module()


def _row(cwa_value="1", hardcover_value="1", cwa_changed_at=None,
         last_synced_at=None):
    return types.SimpleNamespace(
        cwa_value=cwa_value,
        hardcover_value=hardcover_value,
        cwa_changed_at=cwa_changed_at,
        last_synced_at=last_synced_at,
    )


@pytest.mark.unit
class TestHardcoverListTagConflict:
    def test_hardcover_list_removal_removes_stale_cwa_tag(self):
        row = _row(
            cwa_value="1",
            hardcover_value="1",
            cwa_changed_at=None,
            last_synced_at=datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc),
        )

        action = state_sync._list_tag_action(
            row,
            local_has_tag=True,
            hc_has_tag=False,
            hardcover_changed_at=datetime(2026, 5, 2, 8, 48, tzinfo=timezone.utc),
        )

        assert action == state_sync.LIST_TAG_ACTION_PULL_REMOVE

    def test_newer_cwa_tag_adds_book_back_to_hardcover_list(self):
        last_sync = datetime(2026, 5, 2, 8, 0, tzinfo=timezone.utc)
        cwa_change = last_sync + timedelta(minutes=30)
        hc_change = last_sync + timedelta(minutes=10)
        row = _row(
            cwa_value="0",
            hardcover_value="1",
            cwa_changed_at=cwa_change,
            last_synced_at=last_sync,
        )

        action = state_sync._list_tag_action(
            row,
            local_has_tag=True,
            hc_has_tag=False,
            hardcover_changed_at=hc_change,
        )

        assert action == state_sync.LIST_TAG_ACTION_PUSH_ADD

    def test_initial_local_tag_still_seeds_hardcover_list(self):
        row = _row(cwa_value=None, hardcover_value=None, last_synced_at=None)

        action = state_sync._list_tag_action(
            row,
            local_has_tag=True,
            hc_has_tag=False,
            hardcover_changed_at=None,
        )

        assert action == state_sync.LIST_TAG_ACTION_PUSH_ADD
