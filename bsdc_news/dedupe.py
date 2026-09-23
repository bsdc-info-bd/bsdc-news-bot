"""Duplicate detection: canonical URLs, title fingerprints and fuzzy
clustering of the same story reported by several outlets."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

STOPWORDS = frozenset(["a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "can't", "cannot", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "let", "me", "more", "most", "my", "new", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours", "out", "over", "own", "same", "says", "she", "should", "so", "some", "such", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours", "report", "reports", "reportedly", "according", "update", "updated", "breaking", "exclusive", "via", "here's", "heres", "what's", "whats", "how's", "hows", "it's", "its", "you'll", "youll"])

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.'’][a-z0-9]+)*")


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return [t.replace("’", "'") for t in _TOKEN_RE.findall(text)]


def keywords(text: str) -> set[str]:
    return {t for t in tokens(text) if t not in STOPWORDS and (len(t) > 2 or t.isdigit())}


def title_fingerprint(title: str) -> str:
    """Order-independent fingerprint: the same headline with re-ordered words matches."""
    words = sorted(keywords(title))
    return " ".join(words[:12])


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def title_similarity(a: str, b: str) -> float:
    ka, kb = keywords(a), keywords(b)
    jac = jaccard(ka, kb)
    # containment catches "Apple launches X" vs "Apple launches X with Y and Z"
    contain = len(ka & kb) / min(len(ka), len(kb)) if ka and kb else 0.0
    seq = SequenceMatcher(None, " ".join(sorted(ka)), " ".join(sorted(kb))).ratio()
    return max(jac, 0.85 * contain, 0.9 * seq if jac > 0.25 else 0.0)


def is_near_duplicate(title: str, others, threshold: float = 0.6) -> str | None:
    for other in others:
        if title_similarity(title, other) >= threshold:
            return other
    return None


def cluster(items, threshold: float = 0.55, key=lambda it: it.title):
    """Greedy single-pass clustering; returns a list of clusters (lists of items)."""
    clusters: list[list] = []
    reps: list[set[str]] = []
    for item in items:
        kw = keywords(key(item))
        placed = False
        for idx, rep in enumerate(reps):
            if jaccard(kw, rep) >= threshold or (
                kw and rep and len(kw & rep) / min(len(kw), len(rep)) >= max(0.75, threshold + 0.15)
                and len(kw & rep) >= 3
            ):
                clusters[idx].append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])
            reps.append(kw)
    return clusters
