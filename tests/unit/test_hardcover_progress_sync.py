# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for Hardcover progress-only sync behavior."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest


class _FakeLoggerFactory:
    @staticmethod
    def create():
        class _Log:
            def info(self, *args, **kwargs):
                pass

            def warning(self, *args, **kwargs):
                pass

            def error(self, *args, **kwargs):
                pass

        return _Log()


def _load_hardcover_module():
    root = Path(__file__).resolve().parents[2]
    sys.modules.setdefault("cps", types.ModuleType("cps"))
    sys.modules["cps"].logger = _FakeLoggerFactory()
    sys.modules.setdefault("cps.services", types.ModuleType("cps.services"))
    fake_requests = types.ModuleType("requests")
    fake_requests.post = lambda *args, **kwargs: pytest.fail("requests.post should not be called")
    fake_requests.exceptions = types.SimpleNamespace(
        HTTPError=Exception,
        RequestException=Exception,
        Timeout=Exception,
    )
    sys.modules.setdefault("requests", fake_requests)
    spec = importlib.util.spec_from_file_location(
        "cps.services.hardcover",
        root / "cps" / "services" / "hardcover.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["cps.services.hardcover"] = module
    spec.loader.exec_module(module)
    return module


hardcover = _load_hardcover_module()


def _make_client(book, execute_calls=None):
    client = object.__new__(hardcover.HardcoverClient)
    client.parse_identifiers = lambda identifiers: identifiers
    client.get_user_book = lambda identifiers: book
    client.add_book = lambda *args, **kwargs: pytest.fail("add_book should not be called")
    client.change_book_status = lambda *args, **kwargs: pytest.fail("change_book_status should not be called")

    def execute(query, variables=None):
        if execute_calls is not None:
            execute_calls.append({"query": query, "variables": variables or {}})
        return {}

    client.execute = execute
    return client


def _reading_book():
    return {
        "id": 10,
        "status_id": hardcover.STATUS_READING,
        "book_id": 20,
        "edition": {"id": 30, "pages": 200},
        "user_book_reads": [
            {
                "id": 40,
                "started_at": "2026-01-01",
                "finished_at": None,
                "edition_id": 30,
                "progress_pages": 0,
            }
        ],
    }


@pytest.mark.unit
class TestHardcoverProgressOnlySync:
    def test_skips_missing_hardcover_book(self):
        execute_calls = []
        client = _make_client(None, execute_calls)

        client.update_reading_progress({"hardcover-id": "20"}, 50)

        assert execute_calls == []

    def test_skips_book_that_is_not_currently_reading(self):
        execute_calls = []
        book = _reading_book()
        book["status_id"] = hardcover.STATUS_WANT_TO_READ
        client = _make_client(book, execute_calls)

        client.update_reading_progress({"hardcover-id": "20"}, 50)

        assert execute_calls == []

    def test_updates_progress_for_currently_reading_book(self):
        execute_calls = []
        client = _make_client(_reading_book(), execute_calls)

        client.update_reading_progress({"hardcover-id": "20"}, 50)

        assert len(execute_calls) == 1
        variables = execute_calls[0]["variables"]
        assert variables["readId"] == 40
        assert variables["pages"] == 100
        assert variables["editionId"] == 30
        assert variables["startedAt"] == "2026-01-01"
        assert variables["finishedAt"] is None

    def test_progress_at_100_does_not_mark_hardcover_book_finished(self):
        execute_calls = []
        client = _make_client(_reading_book(), execute_calls)

        client.update_reading_progress({"hardcover-id": "20"}, 100)

        assert len(execute_calls) == 1
        assert execute_calls[0]["variables"]["pages"] == 200
        assert execute_calls[0]["variables"]["finishedAt"] is None
