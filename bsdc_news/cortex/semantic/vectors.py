"""A from-scratch vector space: feature hashing, PPMI and truncated SVD.

This is the engine's semantic memory. Co-occurrence statistics from the current
feed batch are turned into low-rank word vectors with orthogonal iteration
(power method + deflation), which gives cosine similarity that understands
"battery" and "cell" are related without downloading any model.
"""

import math
import random
from collections import Counter, defaultdict

from ..text.stopwords import content_words
from ..text.tokenize import words

DEFAULT_DIMENSIONS = 64


def hashed_vector(tokens: list[str], dimensions: int = 1024) -> dict[int, float]:
    """Feature hashing (the 'hashing trick'): tokens → sparse fixed-width vector."""
    vector: dict[int, float] = defaultdict(float)
    for token in tokens:
        index = (hash(token) & 0x7FFFFFFF) % dimensions
        sign = 1.0 if (hash(token + "#") & 1) else -1.0
        vector[index] += sign
    total = math.sqrt(sum(value * value for value in vector.values())) or 1.0
    return {index: value / total for index, value in vector.items()}


def cooccurrence(documents: list[str], *, window: int = 5) -> dict[str, Counter]:
    """Word-word co-occurrence counts within a sliding window."""
    matrix: dict[str, Counter] = defaultdict(Counter)
    for document in documents:
        tokens = content_words(words(document))
        for index, token in enumerate(tokens):
            for offset in range(1, window + 1):
                if index + offset >= len(tokens):
                    break
                neighbour = tokens[index + offset]
                weight = 1.0 / offset
                matrix[token][neighbour] += weight
                matrix[neighbour][token] += weight
    return dict(matrix)


def ppmi(matrix: dict[str, Counter], *, floor: float = 0.0) -> dict[str, dict[str, float]]:
    """Positive pointwise mutual information — the standard weighting for SVD word vectors."""
    total = sum(sum(counter.values()) for counter in matrix.values()) or 1.0
    word_totals = {word: sum(counter.values()) for word, counter in matrix.items()}
    out: dict[str, dict[str, float]] = {}
    for word, counter in matrix.items():
        row: dict[str, float] = {}
        for neighbour, count in counter.items():
            joint = count / total
            product = (word_totals[word] / total) * (word_totals[neighbour] / total)
            if product <= 0 or joint <= 0:
                continue
            value = math.log(joint / product)
            if value > floor:
                row[neighbour] = value
        if row:
            out[word] = row
    return out


def _power_iterate(matrix: dict[str, dict[str, float]], vocabulary: list[str],
                   vector: dict[str, float], iterations: int = 12) -> tuple[dict[str, float], float]:
    index = {word: i for i, word in enumerate(vocabulary)}
    current = dict(vector)
    eigenvalue = 0.0
    for _ in range(iterations):
        nxt: dict[str, float] = defaultdict(float)
        for word, value in current.items():
            if not value:
                continue
            for neighbour, weight in matrix.get(word, {}).items():
                nxt[neighbour] += weight * value
        norm = math.sqrt(sum(value * value for value in nxt.values())) or 1.0
        eigenvalue = norm
        current = {word: value / norm for word, value in nxt.items()}
    _ = index
    return current, eigenvalue


def _deflate(matrix: dict[str, dict[str, float]], vector: dict[str, float],
             eigenvalue: float) -> dict[str, dict[str, float]]:
    """Remove the component just found so the next iteration finds a new direction."""
    out: dict[str, dict[str, float]] = {}
    for word, row in matrix.items():
        own = vector.get(word, 0.0) * eigenvalue
        if not own:
            out[word] = dict(row)
            continue
        new_row = {}
        for neighbour, weight in row.items():
            value = weight - own * vector.get(neighbour, 0.0)
            if abs(value) > 1e-6:
                new_row[neighbour] = value
        out[word] = new_row
    return out


class SemanticIndex:
    """Low-rank word vectors built from whatever corpus the caller supplies."""

    def __init__(self, dimensions: int = DEFAULT_DIMENSIONS, seed: int = 7) -> None:
        self.dimensions = dimensions
        self.seed = seed
        self.vectors: dict[str, list[float]] = {}
        self.raw: dict[str, dict[str, float]] = {}
        self.document_count = 0

    def fit(self, documents: list[str], *, window: int = 5, min_count: int = 2) -> "SemanticIndex":
        self.document_count = len(documents)
        matrix = cooccurrence(documents, window=window)
        matrix = {word: counter for word, counter in matrix.items() if sum(counter.values()) >= min_count}
        for counter in matrix.values():
            for neighbour in list(counter):
                if neighbour not in matrix:
                    del counter[neighbour]
        self.raw = ppmi(matrix)
        vocabulary = sorted(self.raw)
        if not vocabulary:
            return self
        rng = random.Random(self.seed)
        residual = {word: dict(row) for word, row in self.raw.items()}
        components: list[dict[str, float]] = []
        for _ in range(min(self.dimensions, max(1, len(vocabulary) // 2))):
            start = {word: rng.uniform(0.5, 1.5) for word in vocabulary}
            vector, eigenvalue = _power_iterate(residual, vocabulary, start)
            if eigenvalue < 1e-4:
                break
            components.append(vector)
            residual = _deflate(residual, vector, eigenvalue)
        for word in vocabulary:
            self.vectors[word] = [round(component.get(word, 0.0), 6) for component in components]
        return self

    def vector(self, word: str) -> list[float]:
        return self.vectors.get(word.lower(), [])

    def word_similarity(self, a: str, b: str) -> float:
        return cosine(self.vector(a), self.vector(b))

    def nearest(self, word: str, *, top: int = 8) -> list[tuple[str, float]]:
        target = self.vector(word)
        if not target:
            return []
        scored = [(candidate, cosine(target, vector))
                  for candidate, vector in self.vectors.items() if candidate != word.lower()]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [(candidate, round(score, 4)) for candidate, score in scored[:top] if score > 0.05]

    def text_vector(self, text: str) -> list[float]:
        """Mean of the content-word vectors — the document embedding."""
        tokens = [token for token in content_words(words(text)) if token in self.vectors]
        if not tokens:
            return []
        size = len(self.vectors[tokens[0]])
        out = [0.0] * size
        for token in tokens:
            for index, value in enumerate(self.vectors[token]):
                out[index] += value
        norm = math.sqrt(sum(value * value for value in out)) or 1.0
        return [round(value / norm, 6) for value in out]

    def text_similarity(self, a: str, b: str) -> float:
        return cosine(self.text_vector(a), self.text_vector(b))

    def related_terms(self, text: str, *, top: int = 10, exclude: set[str] | None = None) -> list[str]:
        """Semantic neighbours of a document: the LSI keyword source."""
        exclude = {word.lower() for word in (exclude or set())}
        exclude |= set(content_words(words(text)))
        target = self.text_vector(text)
        if not target:
            return []
        scored = [(word, cosine(target, vector)) for word, vector in self.vectors.items()
                  if word not in exclude]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [word for word, score in scored[:top] if score > 0.1]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    numerator = sum(x * y for x, y in zip(a, b, strict=True))
    left = math.sqrt(sum(x * x for x in a))
    right = math.sqrt(sum(y * y for y in b))
    return numerator / (left * right) if left and right else 0.0


def bag_vector(tokens: list[str]) -> dict[str, float]:
    counter = Counter(tokens)
    total = sum(counter.values()) or 1
    return {token: count / total for token, count in counter.items()}


def euclidean(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return float("inf")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def manhattan(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return float("inf")
    return sum(abs(x - y) for x, y in zip(a, b, strict=True))
