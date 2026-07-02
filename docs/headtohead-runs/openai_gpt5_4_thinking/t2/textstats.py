from collections import Counter
import string


def word_count(text):
    return len(text.split())


def top_words(text, n):
    counts = Counter()

    for raw_word in text.split():
        word = raw_word.strip(string.punctuation).lower()
        if word:
            counts[word] += 1

    ordered_words = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ordered_words[:n]
