import string
from collections import Counter


def word_count(text):
    return len(text.split())


def top_words(text, n):
    counts = Counter()
    for token in text.split():
        word = token.strip(string.punctuation).lower()
        if word:
            counts[word] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]
