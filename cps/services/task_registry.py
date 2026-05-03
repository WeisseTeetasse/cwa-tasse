# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from cps import logger

log = logger.create()


def _message(task):
    try:
        return str(task.message) if task.message else None
    except Exception:
        return None


def _name(task):
    try:
        return str(task.name)
    except Exception:
        return task.__class__.__name__


def serialize_task(task):
    """Serialize supported CalibreTask instances into durable job specs.

    This intentionally uses explicit adapters instead of pickling task objects.
    """
    cls_name = task.__class__.__name__
    base = {
        "job_type": cls_name,
        "payload": {},
        "name": _name(task),
        "message": _message(task),
        "cancellable": bool(getattr(task, "is_cancellable", False)),
        "max_attempts": 1,
    }

    if cls_name == "TaskHardcoverStateSync":
        user_id = int(getattr(task, "user_id"))
        source = getattr(task, "source", "scheduled")
        base["payload"] = {"user_id": user_id, "source": source, "task_message": _message(task)}
        base["dedupe_key"] = f"hardcover_state_sync:{user_id}"
        # Lock "library" category to serialize against other library writers.
        # The sync is now optimized and chunked to minimize UI blocking.
        base["lock_category"] = "library"
        return base

    if cls_name == "TaskHardcoverProgressPush":
        user_id = int(getattr(task, "user_id"))
        book_id = int(getattr(task, "book_id"))
        base["payload"] = {"user_id": user_id, "book_id": book_id, "source": getattr(task, "source", "kobo_state")}
        base["dedupe_key"] = f"hardcover_progress_push:{user_id}:{book_id}"
        base["lock_category"] = "library"
        return base

    if cls_name == "TaskConvertLibraryRun":
        base["payload"] = {}
        base["dedupe_key"] = "convert_library"
        base["lock_category"] = "library"
        return base

    if cls_name == "TaskEpubFixerRun":
        base["payload"] = {}
        base["dedupe_key"] = "epub_fixer"
        base["lock_category"] = "library"
        return base

    if cls_name == "TaskDuplicateScan":
        base["payload"] = {
            "full_scan": bool(getattr(task, "full_scan", True)),
            "trigger_type": getattr(task, "trigger_type", "manual"),
            "user_id": getattr(task, "user_id", None),
            "task_message": _message(task),
        }
        if not base["payload"]["full_scan"] and base["payload"]["trigger_type"] == "after_import":
            base["dedupe_key"] = "duplicate_scan:after_import"
        return base

    if cls_name == "TaskAutoHardcoverID":
        base["payload"] = {
            "min_confidence": float(getattr(task, "min_confidence", 0.85)),
            "batch_size": int(getattr(task, "batch_size", 50)),
            "rate_limit_delay": float(getattr(task, "rate_limit_delay", 5.0)),
            "max_backoff_errors": int(getattr(task, "max_backoff_errors", 5)),
            "task_message": _message(task),
        }
        base["dedupe_key"] = "auto_hardcover_id"
        base["lock_category"] = "library"
        return base

    if cls_name == "TaskGenerateCoverThumbnails":
        book_id = int(getattr(task, "book_id", -1))
        base["payload"] = {"book_id": book_id, "task_message": _message(task)}
        base["dedupe_key"] = f"cover_thumbnails:{book_id}"
        return base

    if cls_name == "TaskGenerateSeriesThumbnails":
        base["payload"] = {"task_message": _message(task)}
        base["dedupe_key"] = "series_thumbnails"
        return base

    if cls_name == "TaskClearCoverThumbnailCache":
        book_id = int(getattr(task, "book_id", -1))
        base["payload"] = {"book_id": book_id, "task_message": _message(task)}
        base["dedupe_key"] = f"clear_cover_thumbnail_cache:{book_id}"
        return base

    if cls_name == "TaskBackupMetadata":
        base["payload"] = {
            "export_language": getattr(task, "export_language", "en"),
            "translated_title": getattr(task, "translated_title", "Cover"),
            "set_dirty": bool(getattr(task, "set_dirty", False)),
            "task_message": _message(task),
        }
        base["dedupe_key"] = "metadata_backup:set_dirty" if base["payload"]["set_dirty"] else "metadata_backup"
        base["lock_category"] = "library"
        return base

    if cls_name == "TaskReconnectDatabase":
        base["payload"] = {"task_message": _message(task)}
        base["dedupe_key"] = "reconnect_database"
        return base

    if cls_name == "TaskCleanArchivedBooks":
        base["payload"] = {"task_message": _message(task)}
        base["dedupe_key"] = "clean_archived_books"
        return base

    if cls_name == "TaskClean":
        base["payload"] = {"task_message": _message(task)}
        base["dedupe_key"] = "clean_temp"
        return base

    if cls_name == "TaskUpload":
        base["payload"] = {
            "task_message": _message(task),
            "book_title": getattr(task, "book_title", ""),
        }
        return base

    if cls_name == "TaskAutoSend":
        book_id = int(getattr(task, "book_id"))
        user_id = int(getattr(task, "user_id"))
        base["payload"] = {
            "task_message": _message(task),
            "book_id": book_id,
            "user_id": user_id,
            "delay_minutes": int(getattr(task, "delay_minutes", 5)),
        }
        base["dedupe_key"] = f"auto_send:{book_id}:{user_id}"
        return base

    if cls_name == "TaskEmail":
        base["payload"] = {
            "subject": getattr(task, "subject", None),
            "filepath": getattr(task, "filepath", None),
            "attachment": getattr(task, "attachment", None),
            "settings": getattr(task, "settings", None),
            "recipient": getattr(task, "recipient", None),
            "task_message": _message(task),
            "text": getattr(task, "text", None),
            "id": getattr(task, "book_id", 0),
        }
        return base

    if cls_name == "TaskConvert":
        book_id = int(getattr(task, "book_id"))
        settings = getattr(task, "settings", {}) or {}
        old_fmt = (settings.get("old_book_format") or "unknown").lower()
        new_fmt = (settings.get("new_book_format") or "unknown").lower()
        base["payload"] = {
            "file_path": getattr(task, "file_path", None),
            "book_id": book_id,
            "task_message": _message(task),
            "settings": settings,
            "ereader_mail": getattr(task, "ereader_mail", None),
            "user": getattr(task, "user", None),
        }
        base["dedupe_key"] = f"convert:{book_id}:{old_fmt}:{new_fmt}"
        base["lock_category"] = "library"
        return base

    log.warning("Unsupported durable task adapter for %s; falling back to legacy in-process queue", cls_name)
    return None


def create_task(job_type, payload):
    payload = payload or {}

    if job_type == "TaskHardcoverStateSync":
        from cps.tasks.hardcover_state_sync import TaskHardcoverStateSync
        return TaskHardcoverStateSync(
            payload["user_id"],
            task_message=payload.get("task_message"),
            source=payload.get("source", "scheduled"),
        )

    if job_type == "TaskConvertLibraryRun":
        from cps.tasks.ops import TaskConvertLibraryRun
        return TaskConvertLibraryRun()

    if job_type == "TaskEpubFixerRun":
        from cps.tasks.ops import TaskEpubFixerRun
        return TaskEpubFixerRun()

    if job_type == "TaskDuplicateScan":
        from cps.tasks.duplicate_scan import TaskDuplicateScan
        return TaskDuplicateScan(
            full_scan=payload.get("full_scan", True),
            task_message=payload.get("task_message"),
            trigger_type=payload.get("trigger_type", "manual"),
            user_id=payload.get("user_id"),
        )

    if job_type == "TaskAutoHardcoverID":
        from cps.tasks.auto_hardcover_id import TaskAutoHardcoverID
        return TaskAutoHardcoverID(
            min_confidence=payload.get("min_confidence", 0.85),
            batch_size=payload.get("batch_size", 50),
            rate_limit_delay=payload.get("rate_limit_delay", 5.0),
            max_backoff_errors=payload.get("max_backoff_errors", 5),
            task_message=payload.get("task_message"),
        )

    if job_type == "TaskGenerateCoverThumbnails":
        from cps.tasks.thumbnail import TaskGenerateCoverThumbnails
        return TaskGenerateCoverThumbnails(
            book_id=payload.get("book_id", -1),
            task_message=payload.get("task_message", ""),
        )

    if job_type == "TaskGenerateSeriesThumbnails":
        from cps.tasks.thumbnail import TaskGenerateSeriesThumbnails
        return TaskGenerateSeriesThumbnails(task_message=payload.get("task_message", ""))

    if job_type == "TaskClearCoverThumbnailCache":
        from cps.tasks.thumbnail import TaskClearCoverThumbnailCache
        return TaskClearCoverThumbnailCache(
            payload.get("book_id", -1),
            task_message=payload.get("task_message"),
        )

    if job_type == "TaskBackupMetadata":
        from cps.tasks.metadata_backup import TaskBackupMetadata
        return TaskBackupMetadata(
            export_language=payload.get("export_language", "en"),
            translated_title=payload.get("translated_title", "Cover"),
            set_dirty=payload.get("set_dirty", False),
            task_message=payload.get("task_message"),
        )

    if job_type == "TaskReconnectDatabase":
        from cps.tasks.database import TaskReconnectDatabase
        return TaskReconnectDatabase(task_message=payload.get("task_message"))

    if job_type == "TaskCleanArchivedBooks":
        from cps.tasks.database import TaskCleanArchivedBooks
        return TaskCleanArchivedBooks(task_message=payload.get("task_message"))

    if job_type == "TaskClean":
        from cps.tasks.clean import TaskClean
        return TaskClean(task_message=payload.get("task_message"))

    if job_type == "TaskUpload":
        from cps.tasks.upload import TaskUpload
        return TaskUpload(payload.get("task_message"), payload.get("book_title", ""))

    if job_type == "TaskAutoSend":
        from cps.tasks.auto_send import TaskAutoSend
        return TaskAutoSend(
            payload.get("task_message"),
            payload["book_id"],
            payload["user_id"],
            payload.get("delay_minutes", 5),
        )

    if job_type == "TaskEmail":
        from cps.tasks.mail import TaskEmail
        return TaskEmail(
            payload.get("subject"),
            payload.get("filepath"),
            payload.get("attachment"),
            payload.get("settings"),
            payload.get("recipient"),
            payload.get("task_message"),
            payload.get("text"),
            id=payload.get("id", 0),
            internal=True,
        )

    if job_type == "TaskConvert":
        from cps.tasks.convert import TaskConvert
        return TaskConvert(
            payload.get("file_path"),
            payload["book_id"],
            payload.get("task_message"),
            payload.get("settings"),
            payload.get("ereader_mail"),
            payload.get("user"),
        )

    raise ValueError(f"Unsupported durable job type: {job_type}")
