import re
import string
from collections import Counter

def word_count(text):
    return len(text.split())

def top_words(text, n):
    """Return the n most frequent words in *text*.

    Words are compared case‑insensitively and punctuation characters are stripped
    from the beginning and end of each word. The result is a list of ``(word,
    count)`` tuples ordered by descending frequency and then alphabetically for
    ties. If *n* exceeds the number of distinct words, all words are returned.
    """
    # Split on whitespace, strip punctuation, and normalise case.
    words = []
    for raw in text.split():
        cleaned = raw.strip(string.punctuation)
        if cleaned:
            words.append(cleaned.lower())
    freq = Counter(words)
    sorted_items = sorted(freq.items(), key=lambda item: (-item[1], item[0]))
    return sorted_items[:n]
