from textstats import top_words


def test_basic_frequency():
    text = "apple apple banana apple banana cherry"
    assert top_words(text, 3) == [("apple", 3), ("banana", 2), ("cherry", 1)]


def test_tie_breaking_alphabetical():
    text = "delta alpha charlie bravo"
    assert top_words(text, 4) == [
        ("alpha", 1),
        ("bravo", 1),
        ("charlie", 1),
        ("delta", 1),
    ]


def test_case_insensitivity():
    text = "Apple apple APPLE Banana banana"
    assert top_words(text, 2) == [("apple", 3), ("banana", 2)]


def test_strips_edge_punctuation():
    text = "hello, hello! world. (world) 'hello'"
    assert top_words(text, 2) == [("hello", 3), ("world", 2)]


def test_n_larger_than_vocabulary():
    text = "one two two"
    assert top_words(text, 10) == [("two", 2), ("one", 1)]
