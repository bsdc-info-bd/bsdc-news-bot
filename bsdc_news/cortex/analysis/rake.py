"""RAKE — Rapid Automatic Keyword Extraction (Rose et al., 2010), from scratch.

Candidate phrases are cut at stopwords and punctuation, then scored as the sum of
their words' degrees divided by their frequencies. It is fast, unsupervised and
surprisingly good at surfacing multi-word tech phrases.
"""

import re
from collections import Counter

from ..text.stopwords import is_stopword

_STOP = ("a", "an", "the", "and", "or", "but", "of", "in", "on", "at", "to", "for",
         "with", "by", "from", "as", "is", "was", "were", "are", "been", "be", "has",
         "have", "had", "will", "would", "can", "could", "may", "might", "should",
         "must", "it", "its", "this", "that", "these", "those", "he", "she", "they",
         "them", "his", "her", "their", "which", "who", "whom", "what", "when",
         "where", "why", "how", "not", "no")
_SPLITTER = re.compile(
    r"(?:\b(?:" + "|".join(sorted(set(_STOP), key=len, reverse=True)) + r")\b|[^\w\s]|\d+)"
)


def candidate_phrases(text: str, *, max_words: int = 5) -> list[str]:
    """Split text into RAKE candidate phrases."""
    lowered = re.sub(r"\s+", " ", (text or "").lower())
    out: list[str] = []
    for piece in _SPLITTER.split(lowered):
        phrase = piece.strip()
        if not phrase:
            continue
        tokens = phrase.split()
        if not tokens or len(tokens) > max_words:
            continue
        if all(is_stopword(token, domain=False) for token in tokens):
            continue
        if any(len(token) < 2 for token in tokens):
            continue
        out.append(" ".join(tokens))
    return out


def word_scores(phrases: list[str]) -> dict[str, float]:
    """deg(w)/freq(w) over the candidate phrases."""
    frequency: Counter = Counter()
    degree: Counter = Counter()
    for phrase in phrases:
        tokens = phrase.split()
        degree_weight = len(tokens) - 1
        for token in tokens:
            frequency[token] += 1
            degree[token] += degree_weight
    return {token: (degree[token] + frequency[token]) / frequency[token] for token in frequency}


def rake(text: str, *, top: int = 15, max_words: int = 5) -> list[tuple[str, float]]:
    """Top RAKE keyphrases with their scores, best first."""
    phrases = candidate_phrases(text, max_words=max_words)
    if not phrases:
        return []
    scores = word_scores(phrases)
    phrase_scores: dict[str, float] = {}
    for phrase in phrases:
        tokens = phrase.split()
        phrase_scores[phrase] = sum(scores.get(token, 0.0) for token in tokens) / (len(tokens) ** 0.5)
    ranked = sorted(phrase_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    seen: list[tuple[str, float]] = []
    for phrase, score in ranked:
        if any(phrase in existing and existing != phrase for existing, _ in seen):
            continue
        seen.append((phrase, round(score, 4)))
        if len(seen) >= top:
            break
    return seen


def rake_words(text: str, *, top: int = 20) -> dict[str, float]:
    """Per-word RAKE degrees, useful as a keyword prior."""
    scores = word_scores(candidate_phrases(text))
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return dict(ranked[:top])
