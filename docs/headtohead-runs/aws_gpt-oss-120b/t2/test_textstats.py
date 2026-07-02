import pytest
from textstats import top_words

def test_basic_frequency():
    text = "apple banana apple orange banana apple"
    result = top_words(text, 2)
    assert result == [("apple", 3), ("banana", 2)]

def test_tie_breaking_alphabetical():
    text = "cat dog bat"
    result = top_words(text, 3)
    # All have count 1, should be alphabetical
    assert result == [("bat", 1), ("cat", 1), ("dog", 1)]

def test_case_insensitivity():
    text = "Apple apple APPLE banana BANANA"
    result = top_words(text, 2)
    assert result == [("apple", 3), ("banana", 2)]

def test_n_larger_than_vocab():
    text = "one two"
    result = top_words(text, 5)
    # Both words appear once, alphabetical order
    assert result == [("one", 1), ("two", 1)]
