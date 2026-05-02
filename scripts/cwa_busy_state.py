# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta


def _app_db_path():
    base = os.environ.get("CALIBRE_DBPATH") or "/config"
    if base.endswith(".db"):
        return base
    return os.path.join(base, "app.db")


def _stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def _ensure_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS cwa_library_busy_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category VARCHAR NOT NULL UNIQUE,
            owner VARCHAR,
            message VARCHAR,
            job_id INTEGER,
            started_at DATETIME NOT NULL,
            heartbeat_at DATETIME NOT NULL,
            expires_at DATETIME
        )
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS ix_cwa_library_busy_state_category_expires
        ON cwa_library_busy_state (category, expires_at)
    """)


def set_busy(category="library", owner=None, message=None, job_id=None, ttl_seconds=300):
    now = datetime.utcnow()
    expires = now + timedelta(seconds=int(ttl_seconds or 300))
    try:
        with sqlite3.connect(_app_db_path(), timeout=5) as con:
            _ensure_table(con)
            con.execute("""
                INSERT INTO cwa_library_busy_state
                    (category, owner, message, job_id, started_at, heartbeat_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category) DO UPDATE SET
                    owner=excluded.owner,
                    message=excluded.message,
                    job_id=excluded.job_id,
                    heartbeat_at=excluded.heartbeat_at,
                    expires_at=excluded.expires_at
            """, (
                category,
                owner,
                message,
                job_id,
                _stamp(now),
                _stamp(now),
                _stamp(expires),
            ))
    except Exception as e:
        print(f"[cwa-busy-state] WARN: could not set busy state: {e}", flush=True)


def clear_busy(category="library", owner=None):
    try:
        with sqlite3.connect(_app_db_path(), timeout=5) as con:
            _ensure_table(con)
            if owner is None:
                con.execute("DELETE FROM cwa_library_busy_state WHERE category = ?", (category,))
            else:
                con.execute("DELETE FROM cwa_library_busy_state WHERE category = ? AND owner = ?", (category, owner))
    except Exception as e:
        print(f"[cwa-busy-state] WARN: could not clear busy state: {e}", flush=True)


@contextmanager
def busy_state(category="library", owner=None, message=None, job_id=None, ttl_seconds=300):
    set_busy(category, owner, message, job_id, ttl_seconds)
    try:
        yield
    finally:
        clear_busy(category, owner)
