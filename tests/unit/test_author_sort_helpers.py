# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from types import SimpleNamespace

from cps.db import canonical_author_sort_for_authors, order_linked_authors_by_sort
from scripts.repair_author_sort import repair_author_sort


def author(name, sort):
    return SimpleNamespace(name=name, sort=sort)


def test_order_linked_authors_preserves_matching_author_sort_order():
    first = author("First Author", "Author, First")
    second = author("Second Author", "Author, Second")

    ordered = order_linked_authors_by_sort(
        [first, second],
        "Author, Second & Author, First",
    )

    assert ordered == [second, first]


def test_order_linked_authors_falls_back_to_relationship_order_for_stale_sort():
    linked = author("Justin Lee Anderson", "Anderson, Justin Lee")

    ordered = order_linked_authors_by_sort([linked], "LEE ANDERSON, JUSTIN")

    assert ordered == [linked]


def test_canonical_author_sort_repairs_stale_book_author_sort():
    linked = author("Justin Lee Anderson", "Anderson, Justin Lee")

    repaired = canonical_author_sort_for_authors([linked], "LEE ANDERSON, JUSTIN")

    assert repaired == "Anderson, Justin Lee"


def test_repair_author_sort_updates_metadata_db(tmp_path):
    metadata_db = tmp_path / "metadata.db"
    import sqlite3

    with sqlite3.connect(metadata_db) as con:
        con.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, author_sort TEXT)")
        con.execute("CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT, sort TEXT)")
        con.execute("CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER, author INTEGER)")
        con.execute("INSERT INTO books VALUES (38, 'The Bitter Crown', 'LEE ANDERSON, JUSTIN')")
        con.execute("INSERT INTO authors VALUES (24, 'Justin Lee Anderson', 'Anderson, Justin Lee')")
        con.execute("INSERT INTO books_authors_link VALUES (1, 38, 24)")

    dry_run = repair_author_sort(metadata_db, apply=False)

    assert dry_run == [(38, "The Bitter Crown", "LEE ANDERSON, JUSTIN", "Anderson, Justin Lee")]

    repaired = repair_author_sort(metadata_db, apply=True)

    assert repaired == dry_run
    with sqlite3.connect(metadata_db) as con:
        assert con.execute("SELECT author_sort FROM books WHERE id = 38").fetchone()[0] == "Anderson, Justin Lee"
