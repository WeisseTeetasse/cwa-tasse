# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Static checks for the per-user Hardcover state-sync scheduler.

Bug we fixed: the scheduler only registered per-user Hardcover sync jobs
at app boot. If a user enabled sync (or changed the interval) from the
profile UI, the User row was updated but no APScheduler job was added —
so the change was invisible until the container restarted.

The fixed structure:
- schedule.py exposes ``schedule_hardcover_state_sync_for_user`` and
  ``unschedule_hardcover_state_sync_for_user`` that operate on a single user.
- web.py change_profile calls the re-register helper after committing.
- admin.py user-delete calls the unschedule helper so jobs for deleted
  users stop firing.
- background_scheduler.schedule_task accepts ``job_id`` /
  ``replace_existing`` so the per-user job has a stable id and can be
  replaced cleanly.
- The bare ``except Exception: pass`` that hid all failures in
  ``_schedule_hardcover_state_sync`` has been replaced with logging.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEDULE = PROJECT_ROOT / "cps" / "schedule.py"
WEB = PROJECT_ROOT / "cps" / "web.py"
ADMIN = PROJECT_ROOT / "cps" / "admin.py"
BG_SCHEDULER = PROJECT_ROOT / "cps" / "services" / "background_scheduler.py"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestSchedulerWrapperSupportsStableJobId:
    def test_schedule_task_accepts_job_id_and_replace_existing(self):
        src = _read(BG_SCHEDULER)
        # The wrapper must let callers pin a stable APScheduler job id and
        # replace it on subsequent calls — otherwise we can't update a
        # per-user job in place when the user changes their interval.
        sig = re.search(
            r"def schedule_task\(self,([^)]*)\):",
            src, re.DOTALL,
        )
        assert sig, "Could not locate schedule_task signature"
        params = sig.group(1)
        assert "job_id" in params
        assert "replace_existing" in params

    def test_schedule_passes_job_id_through_to_add_job(self):
        src = _read(BG_SCHEDULER)
        # add_job must receive id= and replace_existing= when job_id is given.
        assert 'kwargs["id"] = job_id' in src
        assert 'kwargs["replace_existing"] = replace_existing' in src


class TestPerUserHardcoverHelpers:
    def test_per_user_register_helper_exists(self):
        src = _read(SCHEDULE)
        assert "def schedule_hardcover_state_sync_for_user(" in src
        # It must use a stable job id so re-registration replaces in place.
        assert "_hardcover_state_sync_job_id(" in src
        assert "replace_existing=True" in src

    def test_per_user_helper_removes_existing_job_first(self):
        src = _read(SCHEDULE)
        # The helper drops the prior job so a disabled-sync update actually
        # removes the schedule (and a change-of-interval rebuilds it).
        helper = re.search(
            r"def schedule_hardcover_state_sync_for_user\(.*?\n(.*?)(?=\n\ndef |\nclass )",
            src, re.DOTALL,
        )
        assert helper, "Could not locate schedule_hardcover_state_sync_for_user body"
        body = helper.group(1)
        assert "scheduler.remove_job(" in body

    def test_unschedule_helper_exists(self):
        src = _read(SCHEDULE)
        assert "def unschedule_hardcover_state_sync_for_user(" in src
        assert "_hardcover_state_sync_job_id(" in src


class TestProfileSaveRefreshesSchedule:
    def test_change_profile_reregisters_hardcover_job(self):
        src = _read(WEB)
        # After ub.session.commit() in change_profile we must call the helper
        # so an interval-change or enable/disable change takes effect on the
        # running container instead of waiting for a restart.
        assert "schedule_hardcover_state_sync_for_user(current_user)" in src

    def test_delete_user_unschedules_hardcover_job(self):
        src = _read(ADMIN)
        assert "unschedule_hardcover_state_sync_for_user(content.id)" in src


class TestSilentSwallowingRemoved:
    def test_boot_scheduler_logs_failures_instead_of_passing_silently(self):
        src = _read(SCHEDULE)
        # The old `except Exception: pass` block in _schedule_hardcover_state_sync
        # made boot-time failures invisible. The replacement must log.
        boot_block = re.search(
            r"def _schedule_hardcover_state_sync\(.*?\n(.*?)(?=\n\ndef )",
            src, re.DOTALL,
        )
        assert boot_block, "Could not locate _schedule_hardcover_state_sync body"
        body = boot_block.group(1)
        # Per-user failures must be logged (not silently swallowed).
        assert "log.warning(" in body
        # The bare `except Exception: pass` that ate everything must be gone.
        assert not re.search(r"except Exception:\s*\n\s*#[^\n]*\n\s*pass\b", body)
