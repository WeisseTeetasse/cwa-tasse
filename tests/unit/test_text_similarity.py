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
