# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import signal
import threading
import time

from cps import create_app, logger
from cps.services import job_queue, task_registry
from cps.services.worker import STAT_CANCELLED, STAT_ENDED, STAT_FAIL, STAT_FINISH_SUCCESS, STAT_STARTED, STAT_WAITING

log = logger.create()


class WorkerProxy:
    """Compatibility proxy passed to legacy CalibreTask.run methods."""

    def add(self, user, task, hidden=False):
        return job_queue.enqueue_task(user, task, hidden=hidden)

    def end_task(self, task_id):
        return job_queue.cancel(task_id)

    def cancel_tasks_for_book(self, book_id):
        # Durable queue cancellation by book id is intentionally conservative here.
        # Existing in-process cancellation paths remain for web-side book deletion.
        return 0


class DurableWorker:
    def __init__(self):
        self.worker_id = job_queue.worker_id()
        self.stop_requested = threading.Event()

    def stop(self, *_args):
        self.stop_requested.set()

    def run_forever(self):
        log.info("CWA durable worker started: %s", self.worker_id)
        job_queue.recover_stale_jobs()
        while not self.stop_requested.is_set():
            claimed = job_queue.claim_next(self.worker_id)
            if not claimed:
                time.sleep(1.0)
                continue
            self.run_job(claimed)
        log.info("CWA durable worker stopped: %s", self.worker_id)

    def run_job(self, claimed):
        log.info("CWA durable worker claimed job %s (%s)", claimed.id, claimed.job_type)
        task = None
        monitor_stop = threading.Event()

        def monitor():
            while not monitor_stop.wait(0.75):
                try:
                    if task is not None:
                        if job_queue.cancel_requested(claimed.id) and getattr(task, "is_cancellable", False):
                            task.stat = STAT_CANCELLED
                        job_queue.heartbeat(
                            claimed.id,
                            progress=getattr(task, "progress", None),
                            message=getattr(task, "message", None),
                        )
                except Exception as ex:
                    log.warning("Failed durable worker heartbeat for job %s: %s", claimed.id, ex)

        monitor_thread = threading.Thread(target=monitor, name=f"cwa-job-heartbeat-{claimed.id}", daemon=True)
        monitor_thread.start()

        try:
            busy = None
            if claimed.lock_category:
                busy = job_queue.LibraryBusy(
                    claimed.lock_category,
                    owner=f"job:{claimed.id}:{claimed.job_type}",
                    message=claimed.name,
                    job_id=claimed.id,
                )
                busy.__enter__()

            task = task_registry.create_task(claimed.job_type, claimed.payload)
            if getattr(task, "stat", None) == STAT_WAITING:
                task.start(WorkerProxy())

            progress = getattr(task, "progress", 1.0)
            message = getattr(task, "message", None)
            if getattr(task, "stat", None) == STAT_CANCELLED:
                job_queue.mark_cancelled(claimed.id, message=message or "Cancelled")
            elif getattr(task, "stat", None) in (STAT_FAIL,):
                job_queue.fail(claimed.id, getattr(task, "error", None) or "Task failed")
            elif getattr(task, "stat", None) in (STAT_FINISH_SUCCESS, STAT_STARTED, STAT_ENDED):
                if getattr(task, "stat", None) == STAT_ENDED:
                    job_queue.mark_cancelled(claimed.id, message=message or "Ended")
                else:
                    job_queue.finish(claimed.id, progress=progress or 1.0, message=message)
            else:
                job_queue.finish(claimed.id, progress=progress or 1.0, message=message)
        except Exception as ex:
            log.error("CWA durable worker failed job %s (%s): %s", claimed.id, claimed.job_type, ex, exc_info=True)
            job_queue.fail(claimed.id, str(ex))
        finally:
            monitor_stop.set()
            monitor_thread.join(timeout=2)
            if claimed.lock_category:
                try:
                    job_queue.clear_library_busy(claimed.lock_category, owner=f"job:{claimed.id}:{claimed.job_type}")
                except Exception:
                    pass


def main():
    app = create_app(start_background=False)
    worker = DurableWorker()
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    with app.app_context():
        worker.run_forever()
