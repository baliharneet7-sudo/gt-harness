import pytest
from textstats import top_words


def test_basic_frequency():
    """Test that the function returns words sorted by frequency (descending)."""
    text = "apple apple banana banana banana cherry"
    result = top_words(text, 3)
    assert result == [("banana", 3), ("apple", 2), ("cherry", 1)]


def test_tie_breaking_alphabetical():
    """Test that ties are broken alphabetically."""
    text = "apple banana cherry date"
    result = top_words(text, 4)
    # All have count 1, should be sorted alphabetically
    assert result == [("apple", 1), ("banana", 1), ("cherry", 1), ("date", 1)]


def test_case_insensitivity():
    """Test that words are case-insensitive."""
    text = "Apple APPLE apple Banana banana"
    result = top_words(text, 2)
    assert result == [("apple", 3), ("banana", 2)]


def test_punctuation_stripping():
    """Test that punctuation is stripped from word edges."""
    text = "Hello, hello! world. World? hello"
    result = top_words(text, 2)
    assert result == [("hello", 3), ("world", 2)]


def test_n_larger_than_vocabulary():
    """Test that requesting more words than exist in vocabulary works."""
    text = "apple banana cherry"
    result = top_words(text, 10)
    assert len(result) == 3
    assert result == [("apple", 1), ("banana", 1), ("cherry", 1)]


def test_empty_text():
    """Test with empty text."""
    result = top_words("", 5)
    assert result == []


def test_n_zero():
    """Test requesting zero words."""
    text = "apple banana cherry"
    result = top_words(text, 0)
    assert result == []


def test_complex_punctuation():
    """Test with various punctuation marks."""
    text = "don't isn't can't don't"
    result = top_words(text, 2)
    # All contractions should be preserved after stripping edge punctuation
    assert result[0][0] == "don't"
    assert result[0][1] == 2


def test_multiple_spaces():
    """Test handling of multiple spaces."""
    text = "word  word   another"
    result = top_words(text, 2)
    assert result == [("word", 2), ("another", 1)]
