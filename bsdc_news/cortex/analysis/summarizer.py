"""Extractive summarisation: four algorithms fused into one ranked summary.

1. **Position** — news puts the facts up front.
2. **Centroid** — distance from the document's mean vector (classic MEAD).
3. **TextRank** — graph centrality among sentences.
4. **MMR** — maximal marginal relevance to remove redundancy from the selection.

Fusing them beats any single scorer and keeps the summary faithful to the source,
which matters because this is what gets published when no rewriting is wanted.
"""

import math
from collections import Counter

from ..text.sentences import split_sentences, word_count
from ..text.stopwords import content_words
from ..text.tokenize import words
from .textrank import cosine, rank_sentences

# Sentences that add no information to a summary.
_NOISE_STARTS = (
    "read more", "see also", "subscribe", "follow us", "share this", "click here",
    "advertisement", "photo:", "image:", "video:", "related:", "also read",
    "continue reading", "tags:", "source:", "via:", "newsletter", "sign up",
    "copyright", "all rights reserved", "for more", "learn more", "download the",
    "install the", "you can also", "note:", "editor's note", "update:",
)


def is_noise(sentence: str) -> bool:
    lowered = sentence.strip().lower()
    if len(lowered) < 20:
        return True
    if any(lowered.startswith(prefix) for prefix in _NOISE_STARTS):
        return True
    if lowered.count("http") or lowered.count("www."):
        return True
    return word_count(sentence) > 90 and sentence.count(",") > 8


def position_scores(count: int) -> list[float]:
    """Front-loaded decay: the lede matters most."""
    return [1.0 / (1.0 + math.log1p(i)) for i in range(count)]


def centroid_scores(sentences: list[str]) -> list[float]:
    """Cosine similarity of each sentence to the document centroid."""
    bags = [Counter(content_words(words(sentence))) for sentence in sentences]
    if not bags:
        return []
    centroid: Counter = Counter()
    for bag in bags:
        centroid.update(bag)
    total = len(bags)
    centroid = Counter({token: count / total for token, count in centroid.items()})
    return [cosine(bag, centroid) for bag in bags]


def length_scores(sentences: list[str], *, ideal: int = 22) -> list[float]:
    """Prefer sentences near the ideal length; penalise fragments and monsters."""
    out = []
    for sentence in sentences:
        count = word_count(sentence)
        out.append(math.exp(-((count - ideal) ** 2) / (2 * (ideal * 0.9) ** 2)))
    return out


def information_scores(sentences: list[str]) -> list[float]:
    """Reward sentences dense in numbers, quotes and named entities."""
    out = []
    for sentence in sentences:
        score = 0.5
        digits = sum(ch.isdigit() for ch in sentence)
        score += min(0.4, digits / 40)
        if '"' in sentence or "'" in sentence:
            score += 0.15
        capitals = sum(1 for token in words(sentence) if token[:1].isupper())
        score += min(0.25, capitals / 12)
        if any(marker in sentence for marker in ("%", "$", "€", "£")):
            score += 0.1
        out.append(min(1.0, score))
    return out


def rank(sentences: list[str], *, weights: dict[str, float] | None = None) -> list[float]:
    """Fused 0..1 score per sentence."""
    if not sentences:
        return []
    weights = weights or {"position": 0.30, "centroid": 0.28, "textrank": 0.24,
                          "length": 0.06, "information": 0.12}
    textrank = rank_sentences(sentences)
    centroid = centroid_scores(sentences)
    position = position_scores(len(sentences))
    length = length_scores(sentences)
    information = information_scores(sentences)
    centroid_peak = max(centroid) or 1.0
    return [
        weights["position"] * position[i]
        + weights["centroid"] * (centroid[i] / centroid_peak)
        + weights["textrank"] * textrank[i]
        + weights["length"] * length[i]
        + weights["information"] * information[i]
        for i in range(len(sentences))
    ]


def mmr_select(sentences: list[str], scores: list[float], *, count: int = 3,
               lambda_: float = 0.72) -> list[int]:
    """Maximal marginal relevance: relevant but not repetitive."""
    remaining = [i for i in range(len(sentences)) if not is_noise(sentences[i])]
    if not remaining:
        remaining = list(range(len(sentences)))
    bags = [Counter(content_words(words(sentence))) for sentence in sentences]
    peak = max(scores) or 1.0
    chosen: list[int] = []
    while remaining and len(chosen) < count:
        best_index, best_value = remaining[0], -1e9
        for index in remaining:
            redundancy = max((cosine(bags[index], bags[other]) for other in chosen), default=0.0)
            value = lambda_ * (scores[index] / peak) - (1 - lambda_) * redundancy
            if value > best_value:
                best_index, best_value = index, value
        chosen.append(best_index)
        remaining.remove(best_index)
    return sorted(chosen)


def summarize(text: str, *, sentences: int = 3, target_words: int = 90,
              keep_order: bool = True) -> list[str]:
    """The top-ranked sentences, returned in document order."""
    pool = split_sentences(text)
    pool = [sentence for sentence in pool if not is_noise(sentence)] or pool
    if not pool:
        return []
    if len(pool) <= sentences:
        return pool
    scores = rank(pool)
    budget = sentences
    if target_words:
        budget = max(sentences, min(len(pool), target_words // 18 or sentences))
    picked = mmr_select(pool, scores, count=budget)
    if not keep_order:
        picked = sorted(picked, key=lambda i: -scores[i])
    return [pool[i] for i in picked]


def summarize_to_words(text: str, *, target_words: int = 90) -> list[str]:
    """Keep adding ranked sentences until the word target is reached."""
    pool = [sentence for sentence in split_sentences(text) if not is_noise(sentence)]
    if not pool:
        return []
    scores = rank(pool)
    order = sorted(range(len(pool)), key=lambda i: -scores[i])
    chosen: list[int] = []
    total = 0
    for index in order:
        count = word_count(pool[index])
        if total + count > target_words * 1.35 and chosen:
            continue
        chosen.append(index)
        total += count
        if total >= target_words:
            break
    return [pool[i] for i in sorted(chosen)]
