"""Tokenisation: words, n-grams and the token shapes the engine reasons over."""

import re
from collections import Counter

WORD = re.compile(
    r"""[A-Za-z]+\d[A-Za-z0-9\-]*"""      # M5, A18, RTX4090, iPhone15, 5G-era names
    r"""|[A-Za-z][A-Za-z'\-]*"""           # ordinary words, hyphens and apostrophes
    r"""|\d[\d,\.]*%?"""                   # 3.5, 1,999, 40%
    r"""|\$[\d,\.]+[mbnk]?"""              # $1,999, $2b
    r"""|[A-Z]{2,}[a-z]*""",               # US, AI, iPhone-ish acronyms
)
ALNUM = re.compile(r"[a-z0-9]+")


def words(text: str) -> list[str]:
    """Lower-cased word tokens, keeping intra-word hyphens and apostrophes."""
    return [token.lower() for token in WORD.findall(text or "")]


def words_cased(text: str) -> list[str]:
    """Same tokens with their original capitalisation (needed for entities)."""
    return list(WORD.findall(text or ""))


def alphanumeric(text: str) -> list[str]:
    """Coarse tokens for fingerprinting — punctuation ignored entirely."""
    return ALNUM.findall((text or "").lower())


def ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
    if n <= 1:
        return [(token,) for token in tokens]
    if len(tokens) < n:
        return []
    return [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def ngram_text(tokens: list[str], n: int) -> list[str]:
    return [" ".join(gram) for gram in ngrams(tokens, n)]


def bigrams(tokens: list[str]) -> list[str]:
    return ngram_text(tokens, 2)


def trigrams(tokens: list[str]) -> list[str]:
    return ngram_text(tokens, 3)


def counts(tokens) -> Counter:
    return Counter(tokens)


def frequencies(tokens: list[str]) -> dict[str, float]:
    """Relative frequency of each token."""
    total = len(tokens)
    if not total:
        return {}
    return {token: count / total for token, count in Counter(tokens).items()}


def unique_ratio(tokens: list[str]) -> float:
    """Type-token ratio: lexical variety, 0..1."""
    if not tokens:
        return 0.0
    return len(set(tokens)) / len(tokens)


def hapax_ratio(tokens: list[str]) -> float:
    """Share of vocabulary that appears exactly once — a richness signal."""
    if not tokens:
        return 0.0
    counter = Counter(tokens)
    return sum(1 for value in counter.values() if value == 1) / len(counter)


def shingles(text: str, k: int = 5) -> set[str]:
    """Word k-shingles for near-duplicate detection."""
    tokens = words(text)
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)}


def char_ngrams(text: str, n: int = 3) -> Counter:
    """Character n-grams, space-padded — used by language detection."""
    padded = f" {(text or '').lower()} "
    return Counter(padded[i:i + n] for i in range(max(0, len(padded) - n + 1)))
