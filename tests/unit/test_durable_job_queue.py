# -*- coding: utf-8 -*-

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine


@pytest.fixture()
def durable_queue_db(tmp_path, monkeypatch):
    from cps import ub

    db_path = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False, connect_args={"timeout": 30})
    ub.Base.metadata.create_all(engine)
    monkeypatch.setattr(ub, "app_DB_path", str(db_path))
    yield db_path
    engine.dispose()


def _job(job_id):
    from cps import ub

    session_factory = ub.get_new_session_instance()
    session = session_factory()
    try:
        return session.query(ub.CWAJobQueue).filter(ub.CWAJobQueue.id == int(job_id)).first()
    finally:
        session.close()
        session_factory.remove()


def test_enqueue_claim_finish_and_dedupe(durable_queue_db):
    from cps.services import job_queue

    first = job_queue.enqueue(
        "ExampleJob",
        payload={"book_id": 1},
        user="dan",
        name="Example",
        message="Queued",
        dedupe_key="example:1",
        cancellable=True,
    )
    second = job_queue.enqueue(
        "ExampleJob",
        payload={"book_id": 1},
        user="dan",
        name="Example",
        dedupe_key="example:1",
    )

    assert second == first

    claimed = job_queue.claim_next("worker-a")
    assert claimed.id == first
    assert claimed.payload == {"book_id": 1}

    job_queue.heartbeat(first, progress=0.5, message="Halfway")
    job_queue.finish(first, message="Done")

    row = _job(first)
    assert row.status == job_queue.STATUS_SUCCESS
    assert row.progress == 1.0
    assert row.message == "Done"


def test_cancel_queued_and_started_jobs(durable_queue_db):
    from cps.services import job_queue

    queued = job_queue.enqueue("QueuedJob", user="dan", name="Queued", cancellable=True)
    assert job_queue.cancel(queued) is True
    assert _job(queued).status == job_queue.STATUS_CANCELLED

    started = job_queue.enqueue("StartedJob", user="dan", name="Started", cancellable=True)
    assert job_queue.claim_next("worker-a").id == started
    assert job_queue.cancel(started) is True
    assert job_queue.cancel_requested(started) is True


def test_stale_job_recovery_and_failure(durable_queue_db):
    from cps import ub
    from cps.services import job_queue

    retryable = job_queue.enqueue("Retryable", user="dan", name="Retryable", max_attempts=2)
    assert job_queue.claim_next("worker-a").id == retryable

    session_factory = ub.get_new_session_instance()
    session = session_factory()
    try:
        row = session.query(ub.CWAJobQueue).filter(ub.CWAJobQueue.id == retryable).first()
        row.heartbeat_at = datetime.utcnow() - timedelta(hours=1)
        session.commit()
    finally:
        session.close()
        session_factory.remove()

    recovered, failed = job_queue.recover_stale_jobs(stale_after_seconds=1)
    assert (recovered, failed) == (1, 0)
    assert _job(retryable).status == job_queue.STATUS_QUEUED

    assert job_queue.claim_next("worker-b").id == retryable
    session_factory = ub.get_new_session_instance()
    session = session_factory()
    try:
        row = session.query(ub.CWAJobQueue).filter(ub.CWAJobQueue.id == retryable).first()
        row.heartbeat_at = datetime.utcnow() - timedelta(hours=1)
        session.commit()
    finally:
        session.close()
        session_factory.remove()

    recovered, failed = job_queue.recover_stale_jobs(stale_after_seconds=1)
    assert (recovered, failed) == (0, 1)
    assert _job(retryable).status == job_queue.STATUS_FAILED


def test_task_status_reads_durable_jobs(durable_queue_db, monkeypatch):
    from cps import tasks_status
    from cps.services import job_queue

    class FakeUser:
        name = "dan"
        locale = "en"

        @staticmethod
        def role_admin():
            return False

    monkeypatch.setattr(tasks_status, "current_user", FakeUser())
    job_queue.enqueue("VisibleJob", user="dan", name="Visible", message="Queued")

    rendered = tasks_status.render_task_status(job_queue.list_queued_tasks())
    assert len(rendered) == 1
    assert rendered[0]["taskMessage"] == "Visible: Queued"
    assert rendered[0]["status"]


def test_library_busy_state(durable_queue_db):
    from cps.services import job_queue

    job_queue.set_library_busy("library", owner="test", message="Importing")
    busy = job_queue.get_library_busy("library")
    assert busy
    assert busy[0]["owner"] == "test"
    assert busy[0]["message"] == "Importing"

    job_queue.clear_library_busy("library", owner="test")
    assert job_queue.get_library_busy("library") == []


def test_manual_hardcover_sync_is_queued_not_inline():
    from pathlib import Path

    web_py = Path(__file__).parents[2] / "cps" / "web.py"
    source = web_py.read_text(encoding="utf-8")

    assert "hardcover_state_sync.sync_user(current_user, source=\"manual\")" not in source
    assert "job_queue.enqueue_task" in source
    assert "TaskHardcoverStateSync(current_user.id, source=\"manual\")" in source
