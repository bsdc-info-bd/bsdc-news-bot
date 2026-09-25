"""Term statistics: TF, TF-IDF, BM25 and positional weighting."""

import math
from collections import Counter

from ..text.tokenize import words


def term_frequency(tokens: list[str]) -> dict[str, float]:
    """Normalised term frequency (count / total)."""
    total = len(tokens)
    if not total:
        return {}
    return {token: count / total for token, count in Counter(tokens).items()}


def log_frequency(tokens: list[str]) -> dict[str, float]:
    """Log-scaled TF, which stops a single repeated word dominating the scores."""
    counter = Counter(tokens)
    return {token: 1 + math.log(count) for token, count in counter.items()}


def augmented_frequency(tokens: list[str]) -> dict[str, float]:
    """0.5 + 0.5 * tf/max(tf) — the classic augmented TF."""
    counter = Counter(tokens)
    if not counter:
        return {}
    top = max(counter.values())
    return {token: 0.5 + 0.5 * count / top for token, count in counter.items()}


def idf(documents: list[list[str]], *, smooth: bool = True) -> dict[str, float]:
    """Inverse document frequency over a corpus of tokenised documents."""
    total = len(documents)
    if not total:
        return {}
    df: Counter = Counter()
    for document in documents:
        df.update(set(document))
    return {token: math.log((total + (1 if smooth else 0)) / (count + (1 if smooth else 0))) + (1 if smooth else 0)
            for token, count in df.items()}


def tfidf(tokens: list[str], idf_map: dict[str, float] | None = None) -> dict[str, float]:
    """TF-IDF for one document; falls back to in-document IDF when no corpus is given."""
    tf = log_frequency(tokens)
    if idf_map is None:
        counter = Counter(tokens)
        total = max(1, len(counter))
        idf_map = {token: math.log(total / count) + 1.0 for token, count in counter.items()}
    return {token: value * idf_map.get(token, 1.0) for token, value in tf.items()}


def bm25(query_tokens: list[str], documents: list[list[str]], *, k1: float = 1.5,
         b: float = 0.75) -> list[tuple[int, float]]:
    """Okapi BM25 ranking of documents against a query — used for related-post links."""
    if not documents:
        return []
    lengths = [len(document) for document in documents]
    average_length = sum(lengths) / len(lengths) or 1.0
    idf_map = idf(documents)
    counters = [Counter(document) for document in documents]
    scores: list[tuple[int, float]] = []
    for index, counter in enumerate(counters):
        score = 0.0
        norm = k1 * (1 - b + b * lengths[index] / average_length)
        for token in query_tokens:
            tf = counter.get(token, 0)
            if not tf:
                continue
            score += idf_map.get(token, 0.0) * (tf * (k1 + 1)) / (tf + norm)
        scores.append((index, score))
    scores.sort(key=lambda pair: (-pair[1], pair[0]))
    return scores


def positional_weights(tokens: list[str], *, decay: float = 0.9) -> dict[str, float]:
    """Words early in a document carry more topical weight."""
    out: dict[str, float] = {}
    for index, token in enumerate(tokens):
        out[token] = max(out.get(token, 0.0), decay ** index)
    return out


def salience(text: str, *, top: int = 20) -> dict[str, float]:
    """One-shot keyword salience: TF-IDF blended with position and title boost."""
    tokens = words(text)
    if not tokens:
        return {}
    scores = tfidf(tokens)
    positions = positional_weights(tokens)
    lead = set(words(text[:160]))
    for token, score in list(scores.items()):
        multiplier = 1.0 + 0.35 * positions.get(token, 0.0) + (0.5 if token in lead else 0.0)
        scores[token] = score * multiplier
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return dict(ranked[:top])


def keyword_density(tokens: list[str], keyword: str) -> float:
    """Share of tokens equal to a keyword (SEO stuffing check)."""
    if not tokens:
        return 0.0
    parts = keyword.lower().split()
    if len(parts) == 1:
        return tokens.count(parts[0]) / len(tokens)
    haystack = " ".join(tokens)
    needle = " ".join(parts)
    return haystack.count(needle) * len(parts) / len(tokens)
