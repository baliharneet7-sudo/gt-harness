from textstats import top_words


def test_top_words_basic_frequency():
    text = "apple banana apple carrot banana apple"

    assert top_words(text, 2) == [("apple", 3), ("banana", 2)]


def test_top_words_tie_breaks_alphabetically():
    text = "banana apple carrot"

    assert top_words(text, 3) == [("apple", 1), ("banana", 1), ("carrot", 1)]


def test_top_words_is_case_insensitive_and_strips_edge_punctuation():
    text = "Hello, hello! HELLO... world; WORLD"

    assert top_words(text, 2) == [("hello", 3), ("world", 2)]


def test_top_words_allows_n_larger_than_vocabulary():
    text = "apple banana apple"

    assert top_words(text, 10) == [("apple", 2), ("banana", 1)]
