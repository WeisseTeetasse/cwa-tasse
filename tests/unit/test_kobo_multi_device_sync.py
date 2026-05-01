from types import SimpleNamespace

from flask import Flask, g
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cps import kobo_sync_status, ub


def _make_session():
    engine = create_engine("sqlite:///:memory:")
    ub.User.__table__.create(bind=engine)
    ub.RemoteAuthToken.__table__.create(bind=engine)
    ub.KoboSyncedBooks.__table__.create(bind=engine)
    return sessionmaker(bind=engine)()


def test_synced_books_are_tracked_per_kobo_token(monkeypatch):
    session = _make_session()
    monkeypatch.setattr(ub, "session", session)
    monkeypatch.setattr(ub, "session_commit", lambda _session=None, *args, **kwargs: (_session or session).commit())
    monkeypatch.setattr(kobo_sync_status, "current_user", SimpleNamespace(id=1))

    app = Flask(__name__)
    with app.test_request_context("/"):
        g.auth_token_id = 11
        kobo_sync_status.add_synced_books(42)
        kobo_sync_status.add_synced_books(42)

        g.auth_token_id = 12
        kobo_sync_status.add_synced_books(42)

        rows = session.query(ub.KoboSyncedBooks).order_by(ub.KoboSyncedBooks.remote_auth_token_id).all()
        assert [(row.book_id, row.remote_auth_token_id) for row in rows] == [(42, 11), (42, 12)]


def test_remove_synced_book_can_target_one_kobo_token(monkeypatch):
    session = _make_session()
    monkeypatch.setattr(ub, "session", session)
    monkeypatch.setattr(ub, "session_commit", lambda _session=None, *args, **kwargs: (_session or session).commit())
    monkeypatch.setattr(kobo_sync_status, "current_user", SimpleNamespace(id=1))

    session.add_all([
        ub.KoboSyncedBooks(user_id=1, book_id=42, remote_auth_token_id=11),
        ub.KoboSyncedBooks(user_id=1, book_id=42, remote_auth_token_id=12),
    ])
    session.commit()

    kobo_sync_status.remove_synced_book(42, remote_auth_token_id=11)

    rows = session.query(ub.KoboSyncedBooks).all()
    assert len(rows) == 1
    assert rows[0].remote_auth_token_id == 12
