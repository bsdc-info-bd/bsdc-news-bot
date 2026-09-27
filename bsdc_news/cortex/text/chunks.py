"""Noun-phrase chunking — the bridge between POS tags and keyphrases.

Keyphrases ("under-display camera", "AI chip shortage") are worth far more than
single words for both SEO and headline writing, so every analysis path asks this
module for chunks rather than re-deriving them.
"""

import re
from dataclasses import dataclass

from .pos import DETERMINERS, PREPOSITIONS, Tagged, tag_text
from .stopwords import is_stopword

_VALID_PHRASE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '\-/&\.]*[A-Za-z0-9]$")
_LEADING_NOISE = re.compile(r"^(?:the|a|an|this|that|these|those|of|in|on|for|and|or|to|with|from|by|at|its|his|her|their)\s+",
                            re.IGNORECASE)


@dataclass
class Chunk:
    text: str
    tokens: tuple[str, ...]
    start: int
    end: int
    proper: bool = False
    head: str = ""

    @property
    def length(self) -> int:
        return len(self.tokens)


def chunk_sentence(sentence: str) -> list[Chunk]:
    """Extract noun phrases from one sentence."""
    tagged = tag_text(sentence)
    chunks: list[Chunk] = []
    current: list[Tagged] = []
    for item in tagged:
        if item.tag in {"NN", "NNS", "NNP", "NNPS", "JJ", "JJR", "JJS", "VBG", "CD"}:
            current.append(item)
            continue
        if current:
            chunk = _build(current)
            if chunk:
                chunks.append(chunk)
            current = []
    if current:
        built = _build(current)
        if built:
            chunks.append(built)
    return chunks


def _build(items: list[Tagged]) -> Chunk | None:
    # Drop leading determiners/adjectives that add nothing.
    while items and (items[0].lemma in DETERMINERS or items[0].token.lower() in DETERMINERS):
        items = items[1:]
    while items and items[-1].tag in {"JJ", "CD"} and len(items) > 1:
        items = items[:-1]
    if not items:
        return None
    text = " ".join(item.token for item in items)
    text = _LEADING_NOISE.sub("", text).strip()
    if not text or not _VALID_PHRASE.match(text):
        return None
    tokens = tuple(item.lemma for item in items)
    if len(text) < 3 or is_stopword(text):
        return None
    if all(is_stopword(token) for token in tokens):
        return None
    proper = all(item.is_proper for item in items if item.tag != "CD") and any(item.is_proper for item in items)
    head = items[-1].lemma
    return Chunk(text=text, tokens=tokens, start=items[0].index, end=items[-1].index,
                 proper=proper, head=head)


def chunks(text: str) -> list[Chunk]:
    """Chunks across a whole document, in order."""
    from .sentences import split_sentences

    out: list[Chunk] = []
    for sentence in split_sentences(text):
        out.extend(chunk_sentence(sentence))
    return out


def phrases(text: str, *, max_words: int = 5, proper_only: bool = False) -> list[str]:
    """Distinct noun phrases, longest-first inside each length class."""
    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    for chunk in chunks(text):
        if chunk.length > max_words:
            continue
        if proper_only and not chunk.proper:
            continue
        key = chunk.text.lower()
        counts[key] = counts.get(key, 0) + 1
        # Keep the best-cased surface form: "iPhone 17 Pro" beats "iphone 17 pro".
        if key not in display or _capital_score(chunk.text) > _capital_score(display[key]):
            display[key] = chunk.text
    return [display[key] for key in sorted(counts, key=lambda k: (-counts[k], k))]


def _capital_score(text: str) -> int:
    return sum(1 for ch in text if ch.isupper())


def base_phrases(text: str) -> set[str]:
    """Noun phrases that contain no preposition — the cleanest keyphrase candidates."""
    out = set()
    for chunk in chunks(text):
        if any(token in PREPOSITIONS for token in chunk.tokens):
            continue
        out.add(chunk.text.lower())
    return out
