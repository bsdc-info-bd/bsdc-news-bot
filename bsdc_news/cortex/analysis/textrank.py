"""TextRank: PageRank over a similarity graph (Mihalcea & Tarau, 2004).

Used twice — over sentences for extractive summarisation and over words for
single-word keyword ranking. Pure Python, deterministic, no dependencies.
"""

import math
from collections import Counter

from ..text.stopwords import content_words
from ..text.tokenize import words


def cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    overlap = set(a) & set(b)
    if not overlap:
        return 0.0
    numerator = sum(a[token] * b[token] for token in overlap)
    return numerator / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def pagerank(matrix: list[list[float]], *, damping: float = 0.85, iterations: int = 60,
             tolerance: float = 1e-7) -> list[float]:
    """Iterative PageRank on a dense weighted adjacency matrix."""
    size = len(matrix)
    if size == 0:
        return []
    if size == 1:
        return [1.0]
    scores = [1.0 / size] * size
    outgoing = [sum(row) for row in matrix]
    for _ in range(iterations):
        previous = list(scores)
        for i in range(size):
            rank = 0.0
            for j in range(size):
                if i == j or not outgoing[j]:
                    continue
                rank += matrix[j][i] / outgoing[j] * previous[j]
            dangling = sum(previous[j] for j in range(size) if not outgoing[j]) / size
            scores[i] = (1 - damping) / size + damping * (rank + dangling)
        total = sum(scores) or 1.0
        scores = [score / total for score in scores]
        if max(abs(scores[i] - previous[i]) for i in range(size)) < tolerance:
            break
    return scores


def sentence_graph(sentences: list[str], *, window: int = 0) -> list[list[float]]:
    """Bag-of-words cosine similarity between every sentence pair."""
    bags = [Counter(content_words(words(sentence))) for sentence in sentences]
    size = len(bags)
    matrix = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(size):
            if i == j:
                continue
            if window and abs(i - j) > window:
                continue
            matrix[i][j] = cosine(bags[i], bags[j])
    return matrix


def rank_sentences(sentences: list[str], *, damping: float = 0.85) -> list[float]:
    """TextRank score per sentence, normalised 0..1."""
    if not sentences:
        return []
    scores = pagerank(sentence_graph(sentences), damping=damping)
    top = max(scores) or 1.0
    return [score / top for score in scores]


def rank_words(text: str, *, top: int = 20, cooccurrence: int = 4) -> list[tuple[str, float]]:
    """TextRank keyword extraction over a co-occurrence window."""
    tokens = content_words(words(text))
    if len(tokens) < 3:
        return [(token, 1.0) for token in dict.fromkeys(tokens)][:top]
    vocabulary = list(dict.fromkeys(tokens))
    index = {token: i for i, token in enumerate(vocabulary)}
    matrix = [[0.0] * len(vocabulary) for _ in vocabulary]
    for start in range(len(tokens)):
        for offset in range(1, cooccurrence + 1):
            end = start + offset
            if end >= len(tokens):
                break
            i, j = index[tokens[start]], index[tokens[end]]
            if i == j:
                continue
            matrix[i][j] += 1.0
            matrix[j][i] += 1.0
    scores = pagerank(matrix)
    ranked = sorted(zip(vocabulary, scores, strict=True), key=lambda pair: (-pair[1], pair[0]))
    return [(token, round(score, 5)) for token, score in ranked[:top]]
