# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from . import calibre_db, db, logger, ub
from .services import hardcover

log = logger.create()

SYNC_KEY_CURRENTLY_READING = "currently_reading"
SYNC_KEY_READ_STATUS = "read_status"
SYNC_KEY_LIST_TAG = "list_tag"

POLL_INTERVALS = (0, 5, 15, 30, 60, 360, 1440)
DEFAULT_CURRENTLY_READING_SHELF = "Currently Reading"
DEFAULT_LIST_TAG = "Up Next"


def _now():
    return datetime.now(timezone.utc)


def _as_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_hc_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _hc_timestamp(item):
    return _parse_hc_time((item or {}).get("updated_at") or (item or {}).get("created_at")) or _now()


def _truth(value):
    return "1" if value else "0"


def _enabled(user):
    return bool(getattr(user, "hardcover_state_sync_enabled", False) or
                getattr(user, "hardcover_list_tag_sync_enabled", False))


def normalize_poll_interval(value):
    value = _as_int(value)
    if value not in POLL_INTERVALS:
        return 30
    return value


def get_client(user):
    token = (getattr(user, "hardcover_token", None) or "").replace("Bearer ", "").strip()
    if not token:
        raise hardcover.MissingHardcoverToken("Hardcover API token is required")
    return hardcover.HardcoverClient(token)


def ensure_currently_reading_shelf(user, commit=False):
    """Return the configured normal CWA shelf, creating the default one when needed."""
    shelf_id = _as_int(getattr(user, "hardcover_state_sync_shelf_id", None))
    shelf = None
    if shelf_id:
        shelf = ub.session.query(ub.Shelf).filter(
            ub.Shelf.id == shelf_id,
            ub.Shelf.user_id == int(user.id)
        ).first()
    if not shelf:
        shelf = ub.session.query(ub.Shelf).filter(
            ub.Shelf.user_id == int(user.id),
            ub.Shelf.is_public == 0,
            ub.Shelf.name == DEFAULT_CURRENTLY_READING_SHELF
        ).first()
    if not shelf:
        shelf = ub.Shelf(name=DEFAULT_CURRENTLY_READING_SHELF, is_public=0, user_id=int(user.id))
        ub.session.add(shelf)
        ub.session.flush()
        log.info("Hardcover state sync: created CWA Currently Reading shelf for user %s.", user.id)
    if getattr(user, "hardcover_state_sync_shelf_id", None) != shelf.id:
        user.hardcover_state_sync_shelf_id = shelf.id
        ub.session.merge(user)
    if commit:
        ub.session.commit()
    return shelf


def get_normal_shelves(user):
    return ub.session.query(ub.Shelf).filter(
        ub.Shelf.user_id == int(user.id),
        ub.Shelf.is_public == 0
    ).order_by(ub.Shelf.name.asc()).all()


def fetch_hardcover_lists(user):
    if not getattr(user, "hardcover_token", None):
        return []
    return get_client(user).get_lists()


def _book_identifier_map(book):
    result = {}
    for identifier in getattr(book, "identifiers", []) or []:
        key = (identifier.type or "").lower()
        if key in ("hardcover-id", "hardcover-edition", "hardcover-slug", "isbn"):
            result[key] = identifier.val
    return result


def _book_hardcover_ids(book):
    ids = _book_identifier_map(book)
    return {
        "book_id": _as_int(ids.get("hardcover-id")),
        "edition_id": _as_int(ids.get("hardcover-edition")),
        "slug": ids.get("hardcover-slug"),
        "isbn": ids.get("isbn"),
    }


def _safe_write_identifiers(book):
    ids = _book_hardcover_ids(book)
    result = {}
    if ids["edition_id"]:
        result["hardcover-edition"] = ids["edition_id"]
    if ids["book_id"]:
        result["hardcover-id"] = ids["book_id"]
    return result


def _local_book_maps():
    books = calibre_db.session.query(db.Books).all()
    by_hc_book = {}
    by_hc_edition = {}
    by_hc_slug = {}
    tagged_books = []
    for book in books:
        ids = _book_hardcover_ids(book)
        if ids["book_id"]:
            by_hc_book[str(ids["book_id"])] = book
        if ids["edition_id"]:
            by_hc_edition[str(ids["edition_id"])] = book
        if ids["slug"]:
            by_hc_slug[str(ids["slug"]).casefold()] = book
        tagged_books.append(book)
    return by_hc_book, by_hc_edition, by_hc_slug, tagged_books


def _match_local_book(hc_item, by_hc_book, by_hc_edition, by_hc_slug):
    edition_id = hc_item.get("edition_id")
    if not edition_id and hc_item.get("edition"):
        edition_id = hc_item.get("edition", {}).get("id")
    book_id = hc_item.get("book_id")
    slug = (hc_item.get("book") or {}).get("slug") or hc_item.get("slug")
    if edition_id and str(edition_id) in by_hc_edition:
        return by_hc_edition[str(edition_id)]
    if book_id and str(book_id) in by_hc_book:
        return by_hc_book[str(book_id)]
    if slug and str(slug).casefold() in by_hc_slug:
        return by_hc_slug[str(slug).casefold()]
    return None


def _sync_row(user_id, book_id, sync_key):
    row = ub.session.query(ub.HardcoverStateSync).filter(
        ub.HardcoverStateSync.user_id == int(user_id),
        ub.HardcoverStateSync.book_id == int(book_id),
        ub.HardcoverStateSync.sync_key == sync_key
    ).first()
    if not row:
        row = ub.HardcoverStateSync(user_id=int(user_id), book_id=int(book_id), sync_key=sync_key)
        ub.session.add(row)
        ub.session.flush()
    return row


def _update_sync_row(row, book=None, hc_item=None, list_book=None, sync_key=None,
                     cwa_value=None, hardcover_value=None, source=None, error=None):
    if book is not None:
        ids = _book_hardcover_ids(book)
        row.hardcover_book_id = ids["book_id"] or row.hardcover_book_id
        row.hardcover_edition_id = ids["edition_id"] or row.hardcover_edition_id
    if hc_item:
        row.hardcover_book_id = _as_int(hc_item.get("book_id")) or row.hardcover_book_id
        row.hardcover_edition_id = _as_int(hc_item.get("edition_id")) or row.hardcover_edition_id
        row.hardcover_user_book_id = _as_int(hc_item.get("id")) or row.hardcover_user_book_id
    if list_book:
        row.hardcover_list_id = _as_int(list_book.get("list_id")) or row.hardcover_list_id
        row.hardcover_list_book_id = _as_int(list_book.get("id")) or row.hardcover_list_book_id
    if sync_key:
        row.sync_key = sync_key
    if cwa_value is not None:
        row.cwa_value = str(cwa_value)
    if hardcover_value is not None:
        row.hardcover_value = str(hardcover_value)
    if source:
        row.last_applied_source = source
    row.last_synced_at = _now()
    row.last_error = error
    ub.session.merge(row)


def _prefer_cwa(row, cwa_value, hardcover_value, hardcover_changed_at):
    """Return True when sync state says a local CWA change should win."""
    if not row:
        return False
    cwa_value = str(cwa_value)
    hardcover_value = str(hardcover_value)
    cwa_changed = (
        (row.cwa_changed_at is not None and
         (row.last_synced_at is None or row.cwa_changed_at > row.last_synced_at)) or
        (row.cwa_value is not None and row.cwa_value != cwa_value)
    )
    hardcover_changed = row.hardcover_value is not None and row.hardcover_value != hardcover_value
    if cwa_changed and not hardcover_changed:
        return True
    if not cwa_changed:
        return False
    if not row.cwa_changed_at or not hardcover_changed_at:
        return False
    return row.cwa_changed_at > hardcover_changed_at


def _is_book_read(user_id, book_id):
    read = ub.session.query(ub.ReadBook).filter(
        ub.ReadBook.user_id == int(user_id),
        ub.ReadBook.book_id == int(book_id)
    ).first()
    return bool(read and read.read_status == ub.ReadBook.STATUS_FINISHED)


def _set_book_read(user_id, book_id):
    read = ub.session.query(ub.ReadBook).filter(
        ub.ReadBook.user_id == int(user_id),
        ub.ReadBook.book_id == int(book_id)
    ).first()
    if not read:
        read = ub.ReadBook(user_id=int(user_id), book_id=int(book_id))
        ub.session.add(read)
    changed = read.read_status != ub.ReadBook.STATUS_FINISHED
    read.read_status = ub.ReadBook.STATUS_FINISHED
    read.last_modified = _now()
    if not read.kobo_reading_state:
        kobo_state = ub.KoboReadingState(user_id=int(user_id), book_id=int(book_id))
        kobo_state.current_bookmark = ub.KoboBookmark(progress_percent=100.0)
        kobo_state.statistics = ub.KoboStatistics()
        read.kobo_reading_state = kobo_state
    elif read.kobo_reading_state.current_bookmark:
        read.kobo_reading_state.current_bookmark.progress_percent = 100.0
    ub.session.merge(read)
    return changed


def _local_progress_percent(user_id, book_id):
    read = ub.session.query(ub.ReadBook).filter(
        ub.ReadBook.user_id == int(user_id),
        ub.ReadBook.book_id == int(book_id)
    ).first()
    if read and read.kobo_reading_state and read.kobo_reading_state.current_bookmark:
        progress = read.kobo_reading_state.current_bookmark.progress_percent
        if progress is not None:
            return float(progress)
    return None


def _book_in_shelf(shelf_id, book_id):
    return ub.session.query(ub.BookShelf).filter(
        ub.BookShelf.shelf == int(shelf_id),
        ub.BookShelf.book_id == int(book_id)
    ).first()


def _add_to_shelf(shelf, book_id):
    if _book_in_shelf(shelf.id, book_id):
        return False
    max_order = ub.session.query(func.max(ub.BookShelf.order)).filter(ub.BookShelf.shelf == shelf.id).scalar()
    shelf.books.append(ub.BookShelf(shelf=shelf.id, book_id=int(book_id), order=(max_order or 0) + 1))
    shelf.last_modified = _now()
    ub.session.merge(shelf)
    return True


def _remove_from_shelf(shelf, book_id):
    row = _book_in_shelf(shelf.id, book_id)
    if not row:
        return False
    ub.session.delete(row)
    shelf.last_modified = _now()
    ub.session.merge(shelf)
    return True


def _has_tag(book, tag_name):
    return any((tag.name or "").casefold() == tag_name.casefold() for tag in book.tags)


def _add_tag(book, tag_name):
    tag_name = (tag_name or DEFAULT_LIST_TAG).strip()
    if not tag_name or _has_tag(book, tag_name):
        return False
    tag = calibre_db.session.query(db.Tags).filter(db.Tags.name.ilike(tag_name)).first()
    if not tag:
        tag = db.Tags(tag_name)
        calibre_db.session.add(tag)
        calibre_db.session.flush()
    book.tags.append(tag)
    calibre_db.session.merge(book)
    return True


def _remove_tag(book, tag_name):
    tag_name = (tag_name or DEFAULT_LIST_TAG).strip()
    removed = False
    for tag in list(book.tags):
        if (tag.name or "").casefold() == tag_name.casefold():
            book.tags.remove(tag)
            removed = True
            if len(tag.books) == 0:
                calibre_db.session.delete(tag)
            break
    if removed:
        calibre_db.session.merge(book)
    return removed


def _determine_removed_currently_reading_status(user, book_id):
    if _is_book_read(user.id, book_id):
        return hardcover.STATUS_READ
    progress = _local_progress_percent(user.id, book_id)
    if progress is not None and progress > 95.0:
        return hardcover.STATUS_READ
    return hardcover.STATUS_WANT_TO_READ


def _matching_list_book(book, list_books):
    if list_books is None:
        return None
    ids = _book_hardcover_ids(book)
    for list_book in list_books:
        if ids["edition_id"] and str(list_book.get("edition_id") or "") == str(ids["edition_id"]):
            return list_book
        if ids["book_id"] and str(list_book.get("book_id") or "") == str(ids["book_id"]):
            return list_book
        list_slug = (list_book.get("book") or {}).get("slug") or list_book.get("slug")
        if ids["slug"] and list_slug and str(list_slug).casefold() == str(ids["slug"]).casefold():
            return list_book
    return None


def _remove_hardcover_list_entry(client, row, list_id, book, selected_list_books=None, list_book=None):
    if list_book is None and selected_list_books is not None:
        list_book = _matching_list_book(book, selected_list_books)
        if list_book is None:
            return False
    list_book_id = _as_int(list_book.get("id")) if list_book else None
    if not list_book_id and row and selected_list_books is None:
        list_book_id = row.hardcover_list_book_id
    if not list_book_id:
        ids = _book_hardcover_ids(book)
        list_book = client.find_list_book(list_id, book_id=ids["book_id"], edition_id=ids["edition_id"])
        list_book_id = list_book.get("id") if list_book else None
    if list_book_id:
        client.delete_list_book(list_book_id)
        if selected_list_books is not None and list_book in selected_list_books:
            selected_list_books.remove(list_book)
        log.info("Hardcover state sync: removed Hardcover list_book %s because CWA tag %s was removed.",
                 list_book_id, getattr(book, "title", ""))
        return True
    return False


def _read_cleanup(user, client, book, selected_list_books=None):
    if not getattr(user, "hardcover_list_tag_sync_enabled", False):
        return
    if not getattr(user, "hardcover_state_read_cleanup_enabled", True):
        return
    tag_name = (getattr(user, "hardcover_list_sync_tag", None) or DEFAULT_LIST_TAG).strip()
    list_id = _as_int(getattr(user, "hardcover_list_sync_list_id", None))
    removed_tag = _remove_tag(book, tag_name)
    removed_list = False
    if list_id and client:
        row = _sync_row(user.id, book.id, SYNC_KEY_LIST_TAG)
        try:
            removed_list = _remove_hardcover_list_entry(client, row, list_id, book, selected_list_books)
            if removed_list:
                _update_sync_row(row, book=book, cwa_value="0", hardcover_value="0", source="cwa")
        except Exception as e:
            row.last_error = str(e)
            log.error("Hardcover state sync: failed read cleanup list removal for CWA book %s: %s", book.id, e)
    if removed_tag or removed_list:
        log.info("Hardcover state sync: read cleanup removed %s tag/list entry for CWA book %s.",
                 tag_name, book.id)


def _push_status_for_book(user, client, book, status_id, reason):
    identifiers = _safe_write_identifiers(book)
    if not identifiers:
        log.warning("Hardcover state sync: skipped CWA book %s, no Hardcover identifier found.", book.id)
        return False
    result = client.change_book_status_by_identifiers(identifiers, status_id)
    if not result:
        log.warning("Hardcover state sync: skipped CWA book %s, no existing Hardcover user book found.", book.id)
        return False
    row = _sync_row(user.id, book.id, SYNC_KEY_CURRENTLY_READING)
    _update_sync_row(row, book=book, hc_item=result, cwa_value=_truth(status_id == hardcover.STATUS_READING),
                     hardcover_value=str(status_id), source="cwa")
    log.info("Hardcover state sync: set Hardcover book %s to status %s from %s.",
             result.get("book_id"), status_id, reason)
    return True


def handle_shelf_added(user, shelf_id, book_id):
    if not _enabled(user) or not getattr(user, "hardcover_state_sync_enabled", False):
        return
    if not getattr(user, "hardcover_state_push_currently_reading", True):
        return
    configured = _as_int(getattr(user, "hardcover_state_sync_shelf_id", None))
    if configured != int(shelf_id):
        return
    row = _sync_row(user.id, book_id, SYNC_KEY_CURRENTLY_READING)
    row.cwa_value = "1"
    row.cwa_changed_at = _now()
    row.last_applied_source = "cwa"
    ub.session.merge(row)
    ub.session.commit()
    if not getattr(user, "hardcover_state_push_immediately", True):
        return
    book = calibre_db.session.query(db.Books).filter(db.Books.id == int(book_id)).first()
    if not book:
        return
    try:
        _push_status_for_book(user, get_client(user), book, hardcover.STATUS_READING, "CWA shelf change")
        ub.session.commit()
    except Exception as e:
        ub.session.rollback()
        log.error("Hardcover state sync: failed pushing shelf add for CWA book %s: %s", book_id, e)


def handle_shelf_removed(user, shelf_id, book_id):
    if not _enabled(user) or not getattr(user, "hardcover_state_sync_enabled", False):
        return
    if not getattr(user, "hardcover_state_push_currently_reading", True):
        return
    configured = _as_int(getattr(user, "hardcover_state_sync_shelf_id", None))
    if configured != int(shelf_id):
        return
    row = _sync_row(user.id, book_id, SYNC_KEY_CURRENTLY_READING)
    row.cwa_value = "0"
    row.cwa_changed_at = _now()
    row.last_applied_source = "cwa"
    ub.session.merge(row)
    ub.session.commit()
    if not getattr(user, "hardcover_state_push_immediately", True):
        return
    book = calibre_db.session.query(db.Books).filter(db.Books.id == int(book_id)).first()
    if not book:
        return
    status_id = _determine_removed_currently_reading_status(user, book_id)
    try:
        client = get_client(user)
        if _push_status_for_book(user, client, book, status_id, "CWA shelf removal"):
            if status_id == hardcover.STATUS_READ:
                _read_cleanup(user, client, book)
        ub.session.commit()
        calibre_db.session.commit()
    except Exception as e:
        ub.session.rollback()
        calibre_db.session.rollback()
        log.error("Hardcover state sync: failed pushing shelf removal for CWA book %s: %s", book_id, e)


def handle_tag_change(user, book, old_tags, new_tags):
    if not _enabled(user) or not getattr(user, "hardcover_list_tag_sync_enabled", False):
        return
    if not getattr(user, "hardcover_list_push_enabled", True):
        return
    tag_name = (getattr(user, "hardcover_list_sync_tag", None) or DEFAULT_LIST_TAG).strip()
    list_id = _as_int(getattr(user, "hardcover_list_sync_list_id", None))
    if not tag_name or not list_id:
        return
    old_has = tag_name.casefold() in {tag.casefold() for tag in old_tags}
    new_has = tag_name.casefold() in {tag.casefold() for tag in new_tags}
    if old_has == new_has:
        return
    row = _sync_row(user.id, book.id, SYNC_KEY_LIST_TAG)
    row.cwa_value = _truth(new_has)
    row.cwa_changed_at = _now()
    row.last_applied_source = "cwa"
    ub.session.merge(row)
    ub.session.commit()
    if not getattr(user, "hardcover_state_push_immediately", True):
        return
    ids = _book_hardcover_ids(book)
    if not ids["book_id"]:
        log.warning("Hardcover state sync: skipped CWA book %s, no Hardcover identifier found.", book.id)
        return
    try:
        client = get_client(user)
        if new_has:
            if _is_book_read(user.id, book.id) and getattr(user, "hardcover_state_read_cleanup_enabled", True):
                _read_cleanup(user, client, book)
            else:
                list_book = client.add_book_to_list(list_id, ids["book_id"], ids["edition_id"])
                _update_sync_row(row, book=book, list_book=list_book, cwa_value="1", hardcover_value="1", source="cwa")
                log.info("Hardcover state sync: added CWA book %s to Hardcover list %s from CWA tag %s.",
                         book.id, list_id, tag_name)
        else:
            if _remove_hardcover_list_entry(client, row, list_id, book):
                _update_sync_row(row, book=book, cwa_value="0", hardcover_value="0", source="cwa")
        ub.session.commit()
    except Exception as e:
        ub.session.rollback()
        row.last_error = str(e)
        log.error("Hardcover state sync: failed pushing tag change for CWA book %s: %s", book.id, e)


def handle_book_marked_read(user, book_id):
    if not _enabled(user):
        return
    if not getattr(user, "hardcover_list_tag_sync_enabled", False):
        return
    if not getattr(user, "hardcover_state_read_cleanup_enabled", True):
        return
    if not getattr(user, "hardcover_state_push_immediately", True):
        return
    book = calibre_db.session.query(db.Books).filter(db.Books.id == int(book_id)).first()
    if not book:
        return
    try:
        _read_cleanup(user, get_client(user), book)
        ub.session.commit()
        calibre_db.session.commit()
    except Exception as e:
        ub.session.rollback()
        calibre_db.session.rollback()
        log.error("Hardcover state sync: failed read cleanup for CWA book %s: %s", book_id, e)


def sync_user(user, source="manual"):
    if not _enabled(user):
        return {"changed": 0, "errors": ["Hardcover state sync is disabled."]}
    client = get_client(user)
    changed = 0
    errors = []
    by_hc_book, by_hc_edition, by_hc_slug, local_books = _local_book_maps()

    shelf = None
    if getattr(user, "hardcover_state_sync_enabled", False):
        shelf = ensure_currently_reading_shelf(user)

    user_books = []
    if getattr(user, "hardcover_state_sync_enabled", False):
        user_books = client.get_user_books()

    selected_list_books = []
    list_id = _as_int(getattr(user, "hardcover_list_sync_list_id", None))
    tag_name = (getattr(user, "hardcover_list_sync_tag", None) or DEFAULT_LIST_TAG).strip()
    if getattr(user, "hardcover_list_tag_sync_enabled", False) and list_id:
        selected_list_books = client.get_list_books(list_id)

    seen_books = set()
    unmatched_hc_books = 0
    for hc_book in user_books:
        local_book = _match_local_book(hc_book, by_hc_book, by_hc_edition, by_hc_slug)
        if not local_book:
            unmatched_hc_books += 1
            log.debug("Hardcover state sync: skipped HC book %s, no matching CWA book found.",
                      hc_book.get("book_id"))
            continue
        seen_books.add(local_book.id)
        status_id = _as_int(hc_book.get("status_id"))
        hc_time = _hc_timestamp(hc_book)

        if getattr(user, "hardcover_state_pull_read_status", True) and status_id == hardcover.STATUS_READ:
            if _set_book_read(user.id, local_book.id):
                changed += 1
                log.info("Hardcover state sync: marked CWA book %s as read from Hardcover.", local_book.id)
            if shelf and _remove_from_shelf(shelf, local_book.id):
                changed += 1
            _read_cleanup(user, client, local_book, selected_list_books)

        if shelf and getattr(user, "hardcover_state_pull_currently_reading", True):
            is_reading = status_id == hardcover.STATUS_READING
            row = _sync_row(user.id, local_book.id, SYNC_KEY_CURRENTLY_READING)
            local_is_reading = bool(_book_in_shelf(shelf.id, local_book.id))
            if (getattr(user, "hardcover_state_push_currently_reading", True) and
                    _prefer_cwa(row, _truth(local_is_reading), str(status_id), hc_time)):
                target_status = hardcover.STATUS_READING if local_is_reading else _determine_removed_currently_reading_status(user, local_book.id)
                if _push_status_for_book(user, client, local_book, target_status, "CWA newer state"):
                    changed += 1
                continue
            if is_reading and _add_to_shelf(shelf, local_book.id):
                changed += 1
                log.info("Hardcover state sync: added CWA book %s to Currently Reading shelf from Hardcover.",
                         local_book.id)
            elif not is_reading and _remove_from_shelf(shelf, local_book.id):
                changed += 1
            row.hardcover_changed_at = hc_time
            _update_sync_row(row, book=local_book, hc_item=hc_book, cwa_value=_truth(is_reading),
                             hardcover_value=str(status_id), source=source)

        if status_id == hardcover.STATUS_READ:
            row = _sync_row(user.id, local_book.id, SYNC_KEY_READ_STATUS)
            row.hardcover_changed_at = hc_time
            _update_sync_row(row, book=local_book, hc_item=hc_book, cwa_value="1",
                             hardcover_value="1", source=source)

    if getattr(user, "hardcover_list_tag_sync_enabled", False) and list_id:
        current_hc_members = {}
        unmatched_hc_list_books = 0
        for list_book in selected_list_books:
            local_book = _match_local_book(list_book, by_hc_book, by_hc_edition, by_hc_slug)
            if not local_book:
                unmatched_hc_list_books += 1
                log.debug("Hardcover state sync: skipped HC list book %s, no matching CWA book found.",
                          list_book.get("book_id"))
                continue
            current_hc_members[local_book.id] = list_book
            row = _sync_row(user.id, local_book.id, SYNC_KEY_LIST_TAG)
            hc_list_time = _hc_timestamp(list_book)
            local_has_tag = _has_tag(local_book, tag_name)
            if (_prefer_cwa(row, _truth(local_has_tag), "1", hc_list_time) and
                    getattr(user, "hardcover_list_push_enabled", True)):
                continue
            if getattr(user, "hardcover_list_pull_enabled", True) and not _is_book_read(user.id, local_book.id):
                if _add_tag(local_book, tag_name):
                    changed += 1
                    log.info("Hardcover state sync: added tag %s to CWA book %s from Hardcover list %s.",
                             tag_name, local_book.id, list_id)
            row.hardcover_changed_at = hc_list_time
            _update_sync_row(row, book=local_book, list_book=list_book, cwa_value=_truth(_has_tag(local_book, tag_name)),
                             hardcover_value="1", source=source)

        if getattr(user, "hardcover_list_push_enabled", True):
            for local_book in local_books:
                local_has_tag = _has_tag(local_book, tag_name)
                hc_list_book = current_hc_members.get(local_book.id)
                hc_has_tag = bool(hc_list_book)
                row = _sync_row(user.id, local_book.id, SYNC_KEY_LIST_TAG)
                row.hardcover_changed_at = _hc_timestamp(hc_list_book) if hc_list_book else row.hardcover_changed_at
                if local_has_tag != hc_has_tag and _prefer_cwa(row, _truth(local_has_tag),
                                                               _truth(hc_has_tag),
                                                               row.hardcover_changed_at):
                    if not local_has_tag:
                        if _remove_hardcover_list_entry(client, row, list_id, local_book,
                                                       selected_list_books, hc_list_book):
                            _update_sync_row(row, book=local_book, cwa_value="0", hardcover_value="0", source=source)
                            changed += 1
                    else:
                        ids = _book_hardcover_ids(local_book)
                        if not ids["book_id"]:
                            log.warning("Hardcover state sync: skipped CWA book %s, no Hardcover identifier found.",
                                        local_book.id)
                            continue
                        list_book = client.add_book_to_list(list_id, ids["book_id"], ids["edition_id"])
                        _update_sync_row(row, book=local_book, list_book=list_book, cwa_value="1",
                                         hardcover_value="1", source=source)
                        changed += 1
                    continue
                if not local_has_tag:
                    if hc_has_tag and getattr(user, "hardcover_list_pull_enabled", True):
                        if _remove_tag(local_book, tag_name):
                            changed += 1
                            _update_sync_row(row, book=local_book, list_book=hc_list_book, cwa_value="0",
                                             hardcover_value="0", source=source)
                    continue
                if _is_book_read(user.id, local_book.id) and getattr(user, "hardcover_state_read_cleanup_enabled", True):
                    _read_cleanup(user, client, local_book, selected_list_books)
                    changed += 1
                    continue
                if hc_has_tag:
                    continue
                ids = _book_hardcover_ids(local_book)
                if not ids["book_id"]:
                    log.warning("Hardcover state sync: skipped CWA book %s, no Hardcover identifier found.",
                                local_book.id)
                    continue
                list_book = client.add_book_to_list(list_id, ids["book_id"], ids["edition_id"])
                _update_sync_row(row, book=local_book, list_book=list_book, cwa_value="1",
                                 hardcover_value="1", source=source)
                changed += 1
                log.info("Hardcover state sync: added CWA book %s to Hardcover list %s from CWA tag %s.",
                         local_book.id, list_id, tag_name)
        if unmatched_hc_list_books:
            log.info("Hardcover state sync: skipped %s Hardcover list books with no matching CWA book.",
                     unmatched_hc_list_books)

    if unmatched_hc_books:
        log.info("Hardcover state sync: skipped %s Hardcover books with no matching CWA book.",
                 unmatched_hc_books)

    user.hardcover_state_last_sync = _now()
    ub.session.merge(user)
    try:
        ub.session.commit()
        calibre_db.session.commit()
    except SQLAlchemyError as e:
        ub.session.rollback()
        calibre_db.session.rollback()
        errors.append(str(e))
        log.error("Hardcover state sync: database error during %s sync for user %s: %s", source, user.id, e)
    return {"changed": changed, "errors": errors}
