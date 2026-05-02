#!/usr/bin/env python3
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cps.db import canonical_author_sort_for_authors  # noqa: E402


def _discover_metadata_db():
    app_db = Path("/config/app.db")
    if app_db.exists():
        with sqlite3.connect(str(app_db), timeout=60) as con:
            row = con.execute("SELECT config_calibre_dir FROM settings LIMIT 1").fetchone()
            if row and row[0]:
                candidate = Path(row[0]) / "metadata.db"
                if candidate.exists():
                    return candidate
    candidate = Path("/calibre-library/metadata.db")
    if candidate.exists():
        return candidate
    return None


def _normalized(value):
    return (value or "").strip().casefold()


def _link_order_column(con):
    columns = {row[1] for row in con.execute("PRAGMA table_info(books_authors_link)").fetchall()}
    return "bal.id" if "id" in columns else "bal.author"


def _book_authors(con, book_id, order_column):
    rows = con.execute(
        f"""
        SELECT a.name, a.sort
        FROM books_authors_link bal
        JOIN authors a ON a.id = bal.author
        WHERE bal.book = ?
        ORDER BY {order_column}
        """,
        (book_id,),
    ).fetchall()
    return [SimpleNamespace(name=row[0], sort=row[1]) for row in rows]


def repair_author_sort(metadata_db, apply=False, book_ids=None, limit=None):
    changed = list()
    with sqlite3.connect(str(metadata_db), timeout=60) as con:
        order_column = _link_order_column(con)
        params = list()
        where = ""
        if book_ids:
            where = "WHERE id IN ({})".format(",".join("?" for _ in book_ids))
            params.extend(book_ids)
        limit_sql = ""
        if limit:
            limit_sql = " LIMIT ?"
            params.append(limit)

        books = con.execute(
            f"SELECT id, title, author_sort FROM books {where} ORDER BY id{limit_sql}",
            params,
        ).fetchall()

        for book_id, title, author_sort in books:
            authors = _book_authors(con, book_id, order_column)
            canonical = canonical_author_sort_for_authors(authors, author_sort)
            if canonical and _normalized(canonical) != _normalized(author_sort):
                changed.append((book_id, title, author_sort, canonical))
                if apply:
                    con.execute("UPDATE books SET author_sort = ? WHERE id = ?", (canonical, book_id))

        if apply:
            con.commit()

    return changed


def main():
    parser = argparse.ArgumentParser(description="Repair books.author_sort values from linked authors.sort values.")
    parser.add_argument("--metadata-db", help="Path to Calibre metadata.db. Defaults to /config/app.db settings.")
    parser.add_argument("--apply", action="store_true", help="Write repairs. Without this, only prints a dry run.")
    parser.add_argument("--book-id", action="append", type=int, dest="book_ids", help="Repair one book id. Repeatable.")
    parser.add_argument("--limit", type=int, help="Limit scanned books, useful for checking a large library.")
    parser.add_argument("--show", type=int, default=20, help="Number of changed rows to print.")
    args = parser.parse_args()

    metadata_db = Path(args.metadata_db) if args.metadata_db else _discover_metadata_db()
    if not metadata_db:
        raise SystemExit("Could not find metadata.db. Pass --metadata-db explicitly.")
    if not metadata_db.exists():
        raise SystemExit(f"metadata.db not found: {metadata_db}")

    changed = repair_author_sort(metadata_db, apply=args.apply, book_ids=args.book_ids, limit=args.limit)
    action = "repaired" if args.apply else "would repair"
    print(f"Author sort repair: {action} {len(changed)} book(s) in {metadata_db}")
    for book_id, title, old, new in changed[:args.show]:
        print(f"{book_id}\t{title}\t{old or ''}\t=>\t{new}")
    if len(changed) > args.show:
        print(f"... {len(changed) - args.show} more")


if __name__ == "__main__":
    main()
