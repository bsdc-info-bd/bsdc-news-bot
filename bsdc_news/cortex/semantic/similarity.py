"""String and set similarity measures.

Ten metrics because no single one is right for every job: near-duplicate
detection wants SimHash/Jaccard, headline variants want edit distance, related-
article links want cosine over content words, and dedupe of titles wants a
normalised token overlap.
"""

import math
import re
from collections import Counter

from ..text.lemma import lemma
from ..text.stopwords import content_words
from ..text.tokenize import alphanumeric, shingles, words

_NONWORD = re.compile(r"[^a-z0-9 ]+")


def normalise_key(text: str) -> str:
    """Canonical comparison key: lower, lemmatised, punctuation-free."""
    tokens = [lemma(token) for token in content_words(words(text))]
    return " ".join(sorted(tokens))


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def dice(a, b) -> float:
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return 2 * len(a & b) / (len(a) + len(b))


def overlap_coefficient(a, b) -> float:
    a, b = set(a), set(b)
    smaller = min(len(a), len(b))
    return len(a & b) / smaller if smaller else 0.0


def cosine_vectors(a: dict, b: dict) -> float:
    """Cosine similarity of two weighted term maps."""
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    numerator = sum(a[key] * b[key] for key in shared)
    denominator = math.sqrt(sum(value * value for value in a.values())) * \
        math.sqrt(sum(value * value for value in b.values()))
    return numerator / denominator if denominator else 0.0


def cosine_lists(a, b) -> float:
    return cosine_vectors(dict(Counter(a)), dict(Counter(b)))


def levenshtein(a: str, b: str) -> int:
    """Classic dynamic-programming edit distance."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
        previous = current
    return previous[-1]


def normalised_levenshtein(a: str, b: str) -> float:
    """1 - edit distance / max length: 1.0 means identical."""
    if not a and not b:
        return 1.0
    longest = max(len(a), len(b))
    return 1.0 - levenshtein(a.lower(), b.lower()) / longest


def jaro(a: str, b: str) -> float:
    if a == b:
        return 1.0
    len_a, len_b = len(a), len(b)
    if not len_a or not len_b:
        return 0.0
    window = max(len_a, len_b) // 2 - 1
    window = max(0, window)
    a_flags = [False] * len_a
    b_flags = [False] * len_b
    matches = 0
    for i, ca in enumerate(a):
        low = max(0, i - window)
        high = min(i + window + 1, len_b)
        for j in range(low, high):
            if not b_flags[j] and ca == b[j]:
                a_flags[i] = b_flags[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    transpositions = 0
    k = 0
    for i, flag in enumerate(a_flags):
        if not flag:
            continue
        while not b_flags[k]:
            k += 1
        if a[i] != b[k]:
            transpositions += 1
        k += 1
    transpositions //= 2
    return (matches / len_a + matches / len_b + (matches - transpositions) / matches) / 3


def jaro_winkler(a: str, b: str, *, scaling: float = 0.1) -> float:
    """Jaro with a prefix bonus — good for brand/product name matching."""
    base = jaro(a.lower(), b.lower())
    prefix = 0
    for ca, cb in zip(a.lower(), b.lower(), strict=False):
        if ca != cb or prefix == 4:
            break
        prefix += 1
    return base + prefix * scaling * (1 - base)


def hamming(a: int, b: int) -> int:
    """Bit distance between two fingerprints."""
    return bin(a ^ b).count("1")


def longest_common_substring(a: str, b: str) -> str:
    if not a or not b:
        return ""
    best = (0, 0)
    previous = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        current = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                current[j] = previous[j - 1] + 1
                if current[j] > best[0]:
                    best = (current[j], i)
        previous = current
    length, end = best
    return a[end - length:end]


def title_similarity(a: str, b: str) -> float:
    """Headline near-duplicate score, blending lemma overlap and edit distance."""
    key_a, key_b = normalise_key(a), normalise_key(b)
    overlap = jaccard(key_a.split(), key_b.split())
    edits = normalised_levenshtein(_NONWORD.sub(" ", a.lower()).strip(),
                                   _NONWORD.sub(" ", b.lower()).strip())
    return round(max(overlap, 0.4 * overlap + 0.6 * edits), 4)


def shingle_similarity(a: str, b: str, *, k: int = 5) -> float:
    """Word-shingle Jaccard — the standard plagiarism/republication check."""
    return jaccard(shingles(a, k), shingles(b, k))


def body_similarity(a: str, b: str) -> float:
    """Combined content similarity used by the duplicate gate."""
    tokens_a, tokens_b = content_words(words(a)), content_words(words(b))
    return round(0.55 * cosine_lists(tokens_a, tokens_b) + 0.25 * jaccard(tokens_a, tokens_b)
                 + 0.20 * shingle_similarity(a, b), 4)


def token_similarity(a: str, b: str) -> float:
    return cosine_lists(alphanumeric(a), alphanumeric(b))


def best_match(needle: str, haystack: list[str], *, scorer=title_similarity) -> tuple[str, float]:
    """The closest string in a list — used to find the matching existing post."""
    best, best_score = "", 0.0
    for candidate in haystack:
        score = scorer(needle, candidate)
        if score > best_score:
            best, best_score = candidate, score
    return best, round(best_score, 4)
