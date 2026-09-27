"""Novelty detection against the published corpus.

A story is only worth publishing if it says something the blog has not already
said. Novelty blends three independent measures so a rehashed press release is
caught even when the wording changes completely.
"""

from dataclasses import dataclass

from ..text.chunks import phrases
from ..text.sentences import split_sentences
from ..text.tokenize import words
from .fingerprint import is_near_duplicate_hash, minhash, minhash_similarity, simhash
from .similarity import body_similarity, shingle_similarity, title_similarity


@dataclass
class NoveltyReport:
    score: float                 # 0..1, higher = more novel
    novel: bool
    reasons: list[str]
    closest_title: str = ""
    closest_similarity: float = 0.0
    new_sentences: int = 0
    new_facts: int = 0

    def as_dict(self) -> dict:
        return {"score": round(self.score, 4), "novel": self.novel,
                "reasons": self.reasons, "closest_title": self.closest_title,
                "closest_similarity": self.closest_similarity,
                "new_sentences": self.new_sentences, "new_facts": self.new_facts}


def score(title: str, text: str, *, published_titles: list[str],
          published_bodies: list[str] | None = None,
          published_hashes: list[int] | None = None,
          threshold: float = 0.42) -> NoveltyReport:
    """How new is this article relative to what the blog already published?"""
    published_bodies = published_bodies or []
    published_hashes = published_hashes or []
    reasons: list[str] = []
    closest_title, closest_similarity = "", 0.0

    for candidate in published_titles:
        similarity = title_similarity(title, candidate)
        if similarity > closest_similarity:
            closest_title, closest_similarity = candidate, similarity
    if closest_similarity >= 0.86:
        reasons.append(f"headline almost identical to '{closest_title[:60]}' ({closest_similarity:.2f})")
    elif closest_similarity >= 0.62:
        reasons.append(f"headline close to '{closest_title[:60]}' ({closest_similarity:.2f})")

    body_worst = 0.0
    for candidate in published_bodies[:400]:
        similarity = body_similarity(text, candidate)
        body_worst = max(body_worst, similarity)
        if body_worst > 0.8:
            break
    if body_worst >= 0.7:
        reasons.append(f"body text overlaps an existing post ({body_worst:.2f})")

    fingerprint = simhash(text)
    hash_hit = any(is_near_duplicate_hash(fingerprint, other) for other in published_hashes)
    if hash_hit:
        reasons.append("SimHash matches an existing post")

    signature = minhash(text, permutations=32)
    minhash_worst = max((minhash_similarity(signature, minhash(candidate, permutations=32))
                         for candidate in published_bodies[:200]), default=0.0)
    if minhash_worst >= 0.5:
        reasons.append(f"shingle overlap with an existing post ({minhash_worst:.2f})")

    new_sentences = 0
    sentences = split_sentences(text)
    for sentence in sentences:
        best = max((shingle_similarity(sentence, candidate) for candidate in published_bodies[:120]),
                   default=0.0)
        if best < 0.35:
            new_sentences += 1
    sentence_share = new_sentences / max(1, len(sentences))

    new_phrases = _new_phrases(text, published_bodies)

    novelty = (
        0.40 * (1 - closest_similarity)
        + 0.30 * (1 - body_worst)
        + 0.15 * (0.0 if hash_hit else 1.0)
        + 0.15 * min(1.0, sentence_share + new_phrases / 8)
    )
    novelty = round(max(0.0, min(1.0, novelty)), 4)
    return NoveltyReport(score=novelty, novel=novelty >= threshold, reasons=reasons,
                         closest_title=closest_title, closest_similarity=round(closest_similarity, 4),
                         new_sentences=new_sentences, new_facts=new_phrases)


def _new_phrases(text: str, published_bodies: list[str]) -> int:
    """Keyphrases that never appear in the published corpus."""
    candidates = {phrase.lower() for phrase in phrases(text) if len(phrase.split()) > 1}
    if not candidates:
        return 0
    corpus = " ".join(published_bodies[:300]).lower()
    return sum(1 for phrase in candidates if phrase not in corpus)


def is_duplicate(title: str, text: str, *, published_titles: list[str],
                 published_bodies: list[str] | None = None, threshold: float = 0.42) -> bool:
    return not score(title, text, published_titles=published_titles,
                     published_bodies=published_bodies or [], threshold=threshold).novel


def angle_difference(title: str, published_titles: list[str]) -> float:
    """How differently this story is framed from previous coverage (0..1)."""
    if not published_titles:
        return 1.0
    tokens = set(words(title))
    overlaps = [len(tokens & set(words(other))) / max(1, len(tokens | set(words(other))))
                for other in published_titles[:50]]
    return round(1 - max(overlaps), 4)
