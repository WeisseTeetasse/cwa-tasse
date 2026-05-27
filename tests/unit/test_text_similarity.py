# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Behavioral tests for cps.utils.text_similarity.

Used by metadata-provider matching to decide if a fetched result actually
corresponds to the user's book. If thresholds shift, the duplicate
detector and the auto-metadata flow produce noticeably worse matches.
"""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_module():
    """Load cps.utils.text_similarity in isolation so the test does not
    trigger cps/__init__.py (which pulls in heavyweight optional deps).
    """
    path = PROJECT_ROOT / "cps" / "utils" / "text_similarity.py"
    spec = importlib.util.spec_from_file_location("_text_similarity", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_m = _load_module()
author_list_similarity = _m.author_list_similarity
calculate_year_similarity = _m.calculate_year_similarity
jaccard_similarity = _m.jaccard_similarity
levenshtein_distance = _m.levenshtein_distance
normalize_string = _m.normalize_string
normalized_levenshtein_similarity = _m.normalized_levenshtein_similarity
tokenize = _m.tokenize


class TestLevenshteinDistance:
    def test_identical_strings_distance_zero(self):
        assert levenshtein_distance("hello", "hello") == 0

    def test_empty_to_string_is_length(self):
        assert levenshtein_distance("", "abc") == 3
        assert levenshtein_distance("abc", "") == 3

    def test_single_char_difference(self):
        assert levenshtein_distance("cat", "bat") == 1

    def test_insertion(self):
        assert levenshtein_distance("cat", "cats") == 1

    def test_deletion(self):
        assert levenshtein_distance("cats", "cat") == 1

    def test_classic_example(self):
        # kitten -> sitting = 3 (substitution k→s, substitution e→i, insert g)
        assert levenshtein_distance("kitten", "sitting") == 3


class TestNormalizeString:
    def test_lowercases(self):
        assert normalize_string("Hello World") == "hello world"

    def test_strips_articles(self):
        assert normalize_string("The Hobbit") == "hobbit"
        assert normalize_string("A Book") == "book"
        assert normalize_string("An Apple") == "apple"

    def test_strips_and_conjunction(self):
        assert "and" not in normalize_string("Tom and Jerry").split()
        assert "&" not in normalize_string("Tom & Jerry").split()

    def test_strips_special_chars(self):
        # Punctuation removed
        assert normalize_string("hello, world!") == "hello world"

    def test_collapses_whitespace(self):
        assert normalize_string("foo    bar") == "foo bar"

    def test_empty_string(self):
        assert normalize_string("") == ""
        assert normalize_string(None) == ""  # type: ignore[arg-type]


class TestNormalizedLevenshteinSimilarity:
    def test_identical_is_one(self):
        assert normalized_levenshtein_similarity("Hello", "Hello") == 1.0

    def test_completely_different_is_low(self):
        # Different strings should score well below 0.5
        assert normalized_levenshtein_similarity("abcdef", "zyxwvu") < 0.3

    def test_empty_strings_are_zero(self):
        # Two empty normalized strings → 0 (not 1, that's the documented behavior)
        assert normalized_levenshtein_similarity("", "") == 0.0

    def test_case_insensitive(self):
        assert normalized_levenshtein_similarity("HELLO", "hello") == 1.0

    def test_article_insensitive(self):
        # "The Hobbit" and "Hobbit" should match perfectly after normalization
        assert normalized_levenshtein_similarity("The Hobbit", "Hobbit") == 1.0


class TestTokenize:
    def test_returns_set_of_words(self):
        assert tokenize("hello world") == {"hello", "world"}

    def test_normalizes_first(self):
        # Articles dropped
        assert tokenize("The Lord of the Rings") == {"lord", "of", "rings"}


class TestJaccardSimilarity:
    def test_identical_is_one(self):
        assert jaccard_similarity("hello world", "hello world") == 1.0

    def test_no_overlap_is_zero(self):
        assert jaccard_similarity("foo bar", "baz qux") == 0.0

    def test_partial_overlap(self):
        # {hello, world} vs {hello, there} → intersection=1, union=3
        assert jaccard_similarity("hello world", "hello there") == pytest.approx(1 / 3)

    def test_both_empty_after_normalization_is_one(self):
        # Documented behavior: both empty → 1.0
        assert jaccard_similarity("the a an", "the a an") == 1.0

    def test_one_empty_is_zero(self):
        assert jaccard_similarity("hello", "") == 0.0


class TestAuthorListSimilarity:
    def test_identical_lists_match(self):
        score, is_and = author_list_similarity(["J.K. Rowling"], ["J.K. Rowling"])
        assert score == 1.0
        assert is_and is True

    def test_empty_input_returns_zero(self):
        assert author_list_similarity([], ["Foo"]) == (0.0, False)
        assert author_list_similarity(["Foo"], []) == (0.0, False)

    def test_minor_formatting_difference_still_matches(self):
        # Spacing / punctuation differences should match above the
        # is_and threshold (>=0.8). This is the common case for
        # comparing metadata from two providers.
        score, is_and = author_list_similarity(["J K Rowling"], ["JK Rowling"])
        assert score > 0.8
        assert is_and is True

    def test_punctuation_difference_matches_perfectly_after_normalize(self):
        score, is_and = author_list_similarity(["JK Rowling"], ["J.K. Rowling"])
        assert score == 1.0
        assert is_and is True

    def test_completely_different_authors_dont_match(self):
        score, is_and = author_list_similarity(["Stephen King"], ["Agatha Christie"])
        assert score < 0.5
        assert is_and is False


class TestCalculateYearSimilarity:
    def test_exact_match(self):
        assert calculate_year_similarity("2020", "2020") == 1.0

    def test_off_by_one(self):
        assert calculate_year_similarity("2020", "2021") == 0.5
        assert calculate_year_similarity("2021", "2020") == 0.5

    def test_far_apart(self):
        assert calculate_year_similarity("2020", "1995") == 0.0

    def test_extracts_year_from_iso_date(self):
        assert calculate_year_similarity("2020-05-12", "2020-12-01") == 1.0

    def test_empty_inputs(self):
        assert calculate_year_similarity("", "2020") == 0.0
        assert calculate_year_similarity("2020", "") == 0.0

    def test_non_year_strings(self):
        assert calculate_year_similarity("not a year", "also not") == 0.0


# ---------------------------------------------------------------------------
# Edge cases — read these to learn the precise contracts.
# ---------------------------------------------------------------------------

class TestNormalizeStringEdgeCases:
    def test_preserves_numbers(self):
        # Numbers are not stripped — useful for "Book 2" style titles.
        # Note: only these are stopwords: ['the','a','an','and','&'].
        # "are", "is", etc. are NOT stopwords — pinned here so a future
        # widening of the stopword list catches our notice.
        assert normalize_string("the book 2 and 3") == "book 2 3"

    def test_preserves_non_ascii_lowercased(self):
        # Cyrillic, Greek, etc. pass through lowercased — no transliteration
        assert normalize_string("Привет МИР") == "привет мир"

    def test_only_stopwords_returns_empty(self):
        # All-stopword input collapses to ""
        assert normalize_string("the a an and &") == ""

    def test_none_returns_empty(self):
        assert normalize_string(None) == ""

    def test_only_punctuation_returns_empty(self):
        assert normalize_string("!@#$%^") == ""

    def test_unicode_punctuation_stripped(self):
        # The regex `[^\w\s]` is Unicode-aware via \w — em-dash is gone
        assert "—" not in normalize_string("foo — bar")


class TestLevenshteinDistanceEdgeCases:
    def test_both_empty(self):
        assert levenshtein_distance("", "") == 0

    def test_single_char_each(self):
        assert levenshtein_distance("a", "a") == 0
        assert levenshtein_distance("a", "b") == 1

    def test_completely_different_lengths(self):
        # Long deletion: minimum edits = length of longer
        assert levenshtein_distance("", "abcdefghij") == 10

    def test_unicode_chars_counted_correctly(self):
        # Single-code-point Unicode → distance 1, not byte length
        assert levenshtein_distance("café", "cafe") == 1


class TestJaccardSimilarityEdgeCases:
    def test_both_normalize_to_empty_returns_one(self):
        # Both inputs reduce to {} after normalization → 1.0 by
        # documented convention (both "empty" → identical)
        assert jaccard_similarity("the", "the") == 1.0
        assert jaccard_similarity("the a an", "the a an") == 1.0

    def test_case_insensitive(self):
        assert jaccard_similarity("HELLO", "hello") == 1.0

    def test_duplicate_tokens_dont_affect_jaccard(self):
        # Set semantics: "hello hello" tokenizes to {"hello"}
        assert jaccard_similarity("hello hello", "hello") == 1.0


class TestAuthorListSimilarityEdgeCases:
    def test_none_returns_zero(self):
        # Defensive: None propagates as "no list" rather than raising
        assert author_list_similarity(None, ["King"]) == (0.0, False)
        assert author_list_similarity(["King"], None) == (0.0, False)

    def test_empty_string_in_list_normalizes_to_empty(self):
        # Empty string normalizes to "" → similarity 0 against any
        # non-empty author → the GOOD author still produces a high score
        # because the function takes per-author max
        score, is_and = author_list_similarity(["", "King"], ["King"])
        # The "" entry pulls the average down; is_and is False because
        # not every author from authors1 has a >0.8 match
        assert 0.0 < score < 1.0
        assert is_and is False

    def test_self_comparison_perfect(self):
        score, is_and = author_list_similarity(
            ["Stephen King", "Joe Hill"], ["Stephen King", "Joe Hill"]
        )
        assert score == 1.0
        assert is_and is True

    def test_different_order_same_authors_perfect(self):
        # Per-author max-best-match → order-independent.
        # Use multi-char names so they survive normalization (single
        # chars like "A" become stopwords or empty after normalize).
        score, is_and = author_list_similarity(
            ["Stephen King", "Joe Hill"], ["Joe Hill", "Stephen King"]
        )
        assert score == 1.0
        assert is_and is True


class TestCalculateYearSimilarityEdgeCases:
    def test_three_digit_year_returns_zero(self):
        # Regex requires \b\d{4}\b — 3 digits don't match
        assert calculate_year_similarity("500", "500") == 0.0

    def test_five_digit_year_returns_zero(self):
        # Same — \b\d{4}\b doesn't match 5-digit
        assert calculate_year_similarity("12345", "12345") == 0.0

    def test_year_extracted_from_within_text(self):
        # Regex finds first 4-digit number anywhere in the string
        assert calculate_year_similarity("foo 2020 bar", "2020") == 1.0

    def test_int_year_accepted(self):
        # Internal str(year1) coercion handles ints
        assert calculate_year_similarity(2020, 2021) == 0.5

    def test_none_returns_zero(self):
        assert calculate_year_similarity(None, "2020") == 0.0
        assert calculate_year_similarity("2020", None) == 0.0


class TestNormalizedLevenshteinSimilarityEdgeCases:
    def test_substring_match_partial(self):
        # "hello" vs "hello world" — substantial but not perfect
        score = normalized_levenshtein_similarity("hello", "hello world")
        assert 0.4 < score < 0.6

    def test_one_normalized_to_empty(self):
        # "the" normalizes to "" → returns 0.0
        assert normalized_levenshtein_similarity("the", "hello") == 0.0

    def test_both_normalized_to_empty(self):
        # Documented edge: both empty → 0.0 (not 1.0)
        # This is intentional: empty strings should not "match" anything
        # in the metadata fuzzy-match flow
        assert normalized_levenshtein_similarity("the", "the") == 0.0
