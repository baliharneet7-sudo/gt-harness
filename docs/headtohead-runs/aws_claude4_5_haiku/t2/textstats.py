import string
from collections import Counter


def word_count(text):
    return len(text.split())


def top_words(text, n):
    """
    Returns the n most frequent words as a list of (word, count) tuples,
    ordered by count descending then alphabetically for ties.
    
    Words are case-insensitive and punctuation is stripped from word edges.
    
    Args:
        text: The input text to analyze
        n: The number of top words to return
        
    Returns:
        A list of (word, count) tuples sorted by count (descending) then alphabetically
    """
    # Convert to lowercase
    text = text.lower()
    
    # Split into words and clean punctuation from edges
    words = []
    for word in text.split():
        # Strip punctuation from both ends
        cleaned = word.strip(string.punctuation)
        if cleaned:  # Only add non-empty words
            words.append(cleaned)
    
    # Count word frequencies
    word_freq = Counter(words)
    
    # Sort by count (descending) then alphabetically for ties
    sorted_words = sorted(word_freq.items(), key=lambda x: (-x[1], x[0]))
    
    # Return top n words
    return sorted_words[:n]
