# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import time
import uuid
from collections import namedtuple
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, text

from cps import logger, ub
from cps.services.worker import (
    QueuedTask,
    STAT_CANCELLED,
    STAT_FAIL,
    STAT_FINISH_SUCCESS,
    STAT_STARTED,
    STAT_WAITING,
)

log = logger.create()

STATUS_QUEUED = "queued"
STATUS_STARTED = "started"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_STARTED)
TERMINAL_STATUSES = (STATUS_SUCCESS, STATUS_FAILED, STATUS_CANCELLED)

DEFAULT_STALE_AFTER_SECONDS = 30 * 60
DEFAULT_JOB_RETENTION = 100

ClaimedJob = namedtuple("ClaimedJob", "id job_type payload name message user_id user_label hidden cancellable lock_category")


def _utcnow():
    return datetime.now(timezone.utc)


def _naive_utcnow():
    # Existing app DB DateTime columns generally store naive datetimes.
    return datetime.utcnow()


def _to_iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def enabled():
    return os.environ.get("CWA_DURABLE_QUEUE", "1").strip().lower() not in ("0", "false", "no", "off")


@contextmanager
def _session_scope():
    session_factory = ub.get_new_session_instance()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        session_factory.remove()


def enqueue(job_type, payload=None, user=None, user_id=None, name=None, message=None, hidden=False,
            cancellable=False, dedupe_key=None, lock_category=None, run_at=None, max_attempts=1):
    if not enabled():
        return None

    payload = payload or {}
    user_label = str(user) if user is not None else "System"
    now = _naive_utcnow()

    with _session_scope() as session:
        if dedupe_key:
            existing = (session.query(ub.CWAJobQueue)
                        .filter(ub.CWAJobQueue.dedupe_key == dedupe_key)
                        .filter(ub.CWAJobQueue.status.in_(ACTIVE_STATUSES))
                        .order_by(ub.CWAJobQueue.id.desc())
                        .first())
            if existing:
                log.debug("Durable job deduped: %s -> %s", dedupe_key, existing.id)
                return existing.id

        row = ub.CWAJobQueue(
            job_type=job_type,
            payload=payload,
            user_id=user_id,
            user_label=user_label,
            name=name or job_type,
            message=message,
            status=STATUS_QUEUED,
            progress=0.0,
            hidden=bool(hidden),
            cancellable=bool(cancellable),
            cancel_requested=False,
            dedupe_key=dedupe_key,
            lock_category=lock_category,
            run_at=run_at,
            created_at=now,
            attempts=0,
            max_attempts=max(1, int(max_attempts or 1)),
        )
        session.add(row)
        session.flush()
        log.info("Queued durable job %s (%s) for %s", row.id, job_type, user_label)
        return row.id


def enqueue_task(user, task, hidden=False, dedupe_key=None):
    from cps.services import task_registry

    spec = task_registry.serialize_task(task)
    if not spec:
        return None
    user_id = getattr(task, "user_id", None)
    return enqueue(
        spec["job_type"],
        payload=spec.get("payload") or {},
        user=user,
        user_id=user_id,
        name=spec.get("name"),
        message=spec.get("message"),
        hidden=hidden,
        cancellable=spec.get("cancellable", False),
        dedupe_key=dedupe_key or spec.get("dedupe_key"),
        lock_category=spec.get("lock_category"),
        max_attempts=spec.get("max_attempts", 1),
    )


def claim_next(worker_id, stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS):
    recover_stale_jobs(stale_after_seconds=stale_after_seconds)
    now = _naive_utcnow()
    with _session_scope() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        row = (session.query(ub.CWAJobQueue)
               .filter(ub.CWAJobQueue.status == STATUS_QUEUED)
               .filter(or_(ub.CWAJobQueue.run_at.is_(None), ub.CWAJobQueue.run_at <= now))
               .order_by(ub.CWAJobQueue.id.asc())
               .first())
        if not row:
            return None
        row.status = STATUS_STARTED
        row.started_at = row.started_at or now
        row.heartbeat_at = now
        row.worker_id = worker_id
        row.attempts = int(row.attempts or 0) + 1
        session.flush()
        return ClaimedJob(
            id=row.id,
            job_type=row.job_type,
            payload=row.payload or {},
            name=row.name,
            message=row.message,
            user_id=row.user_id,
            user_label=row.user_label,
            hidden=row.hidden,
            cancellable=row.cancellable,
            lock_category=row.lock_category,
        )


def heartbeat(job_id, progress=None, message=None):
    now = _naive_utcnow()
    with _session_scope() as session:
        row = session.query(ub.CWAJobQueue).filter(ub.CWAJobQueue.id == int(job_id)).first()
        if not row or row.status != STATUS_STARTED:
            return False
        row.heartbeat_at = now
        if progress is not None:
            row.progress = max(0.0, min(1.0, float(progress)))
        if message is not None:
            row.message = str(message)
        return True


def cancel_requested(job_id):
    with _session_scope() as session:
        row = session.query(ub.CWAJobQueue.cancel_requested).filter(ub.CWAJobQueue.id == int(job_id)).first()
        return bool(row and row[0])


def finish(job_id, progress=1.0, message=None):
    _set_terminal(job_id, STATUS_SUCCESS, progress=progress, message=message, error=None)


def mark_cancelled(job_id, message=None):
    _set_terminal(job_id, STATUS_CANCELLED, progress=1.0, message=message or "Cancelled", error=None)


def fail(job_id, error, retry=False):
    now = _naive_utcnow()
    with _session_scope() as session:
        row = session.query(ub.CWAJobQueue).filter(ub.CWAJobQueue.id == int(job_id)).first()
        if not row:
            return
        row.error = str(error)
        if retry and int(row.attempts or 0) < int(row.max_attempts or 1):
            row.status = STATUS_QUEUED
            row.worker_id = None
            row.heartbeat_at = None
            row.run_at = now + timedelta(seconds=min(300, 15 * max(1, int(row.attempts or 1))))
            row.message = str(error)
        else:
            row.status = STATUS_FAILED
            row.progress = 1.0
            row.finished_at = now
            row.message = str(error)


def cancel(job_id):
    now = _naive_utcnow()
    with _session_scope() as session:
        row = session.query(ub.CWAJobQueue).filter(ub.CWAJobQueue.id == int(job_id)).first()
        if not row:
            return False
        if row.status == STATUS_QUEUED:
            row.status = STATUS_CANCELLED
            row.cancel_requested = True
            row.finished_at = now
            row.progress = 1.0
        elif row.status == STATUS_STARTED:
            row.cancel_requested = True
        return True


def _set_terminal(job_id, status, progress=1.0, message=None, error=None):
    now = _naive_utcnow()
    with _session_scope() as session:
        row = session.query(ub.CWAJobQueue).filter(ub.CWAJobQueue.id == int(job_id)).first()
        if not row:
            return
        row.status = status
        row.progress = max(0.0, min(1.0, float(progress)))
        row.finished_at = now
        row.heartbeat_at = now
        row.error = error
        if message is not None:
            row.message = str(message)


def recover_stale_jobs(stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS):
    cutoff = _naive_utcnow() - timedelta(seconds=stale_after_seconds)
    recovered = 0
    failed = 0
    with _session_scope() as session:
        rows = (session.query(ub.CWAJobQueue)
                .filter(ub.CWAJobQueue.status == STATUS_STARTED)
                .filter(or_(ub.CWAJobQueue.heartbeat_at.is_(None), ub.CWAJobQueue.heartbeat_at < cutoff))
                .all())
        for row in rows:
            if int(row.attempts or 0) < int(row.max_attempts or 1):
                row.status = STATUS_QUEUED
                row.worker_id = None
                row.heartbeat_at = None
                row.message = "Recovered stale worker job"
                recovered += 1
            else:
                row.status = STATUS_FAILED
                row.finished_at = _naive_utcnow()
                row.error = "Worker stopped before completing job"
                failed += 1
    if recovered or failed:
        log.warning("Recovered %s stale durable jobs, failed %s stale durable jobs", recovered, failed)
    return recovered, failed


class DurableTaskView:
    def __init__(self, row):
        self.id = row.id
        self.start_time = row.started_at
        self.end_time = row.finished_at
        self.message = row.message
        self.error = row.error
        self.progress = float(row.progress or 0.0)
        self._name = row.name
        self._status = row.status
        self._is_cancellable = bool(row.cancellable)

    @property
    def name(self):
        return self._name

    @property
    def stat(self):
        if self._status == STATUS_QUEUED:
            return STAT_WAITING
        if self._status == STATUS_STARTED:
            return STAT_STARTED
        if self._status == STATUS_SUCCESS:
            return STAT_FINISH_SUCCESS
        if self._status == STATUS_CANCELLED:
            return STAT_CANCELLED
        return STAT_FAIL

    @property
    def is_cancellable(self):
        return self._is_cancellable and self._status in ACTIVE_STATUSES

    @property
    def runtime(self):
        end = self.end_time or _naive_utcnow()
        start = self.start_time or end
        return end - start


def list_queued_tasks(limit=DEFAULT_JOB_RETENTION, include_hidden=False):
    with _session_scope() as session:
        query = session.query(ub.CWAJobQueue)
        if not include_hidden:
            query = query.filter(ub.CWAJobQueue.hidden == False)  # noqa: E712
        rows = query.order_by(ub.CWAJobQueue.id.desc()).limit(int(limit)).all()
        rows.reverse()
        return [
            QueuedTask(
                num=row.id,
                user=row.user_label or "System",
                added=row.created_at,
                task=DurableTaskView(row),
                hidden=row.hidden,
            )
            for row in rows
        ]


def get_queued_task(job_id):
    with _session_scope() as session:
        row = session.query(ub.CWAJobQueue).filter(ub.CWAJobQueue.id == int(job_id)).first()
        if not row:
            return None
        return QueuedTask(
            num=row.id,
            user=row.user_label or "System",
            added=row.created_at,
            task=DurableTaskView(row),
            hidden=row.hidden,
        )


def worker_id():
    return "{}-{}".format(os.uname().nodename if hasattr(os, "uname") else "worker", uuid.uuid4().hex[:8])


class LibraryBusy:
    def __init__(self, category, owner=None, message=None, job_id=None, ttl_seconds=300):
        self.category = category
        self.owner = owner
        self.message = message
        self.job_id = job_id
        self.ttl_seconds = ttl_seconds

    def __enter__(self):
        set_library_busy(self.category, self.owner, self.message, self.job_id, self.ttl_seconds)
        return self

    def heartbeat(self):
        set_library_busy(self.category, self.owner, self.message, self.job_id, self.ttl_seconds)

    def __exit__(self, exc_type, exc, tb):
        clear_library_busy(self.category, self.owner)


def set_library_busy(category="library", owner=None, message=None, job_id=None, ttl_seconds=300):
    now = _naive_utcnow()
    expires = now + timedelta(seconds=int(ttl_seconds or 300))
    with _session_scope() as session:
        row = session.query(ub.CWALibraryBusyState).filter(ub.CWALibraryBusyState.category == category).first()
        if not row:
            row = ub.CWALibraryBusyState(category=category)
            session.add(row)
        row.owner = owner
        row.message = message
        row.job_id = job_id
        row.started_at = row.started_at or now
        row.heartbeat_at = now
        row.expires_at = expires


def clear_library_busy(category="library", owner=None):
    with _session_scope() as session:
        query = session.query(ub.CWALibraryBusyState).filter(ub.CWALibraryBusyState.category == category)
        if owner is not None:
            query = query.filter(ub.CWALibraryBusyState.owner == owner)
        query.delete(synchronize_session=False)


def get_library_busy(category=None):
    now = _naive_utcnow()
    with _session_scope() as session:
        session.query(ub.CWALibraryBusyState).filter(ub.CWALibraryBusyState.expires_at < now).delete(
            synchronize_session=False
        )
        query = session.query(ub.CWALibraryBusyState)
        if category:
            query = query.filter(ub.CWALibraryBusyState.category == category)
        rows = query.order_by(ub.CWALibraryBusyState.started_at.asc()).all()
        return [
            {
                "category": row.category,
                "owner": row.owner,
                "message": row.message,
                "job_id": row.job_id,
                "started_at": _to_iso(row.started_at),
                "heartbeat_at": _to_iso(row.heartbeat_at),
                "expires_at": _to_iso(row.expires_at),
            }
            for row in rows
        ]
