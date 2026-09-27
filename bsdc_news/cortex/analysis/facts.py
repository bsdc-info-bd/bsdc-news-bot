"""Fact extraction: turn prose into ranked, attributable claims.

The writer composes articles from facts, not from raw sentences, which is what
keeps the output faithful to the source when no external model is involved.
Each fact keeps its sentence index so every claim can be traced back.
"""

import re

from ..text.sentences import split_sentences, word_count
from ..text.stopwords import content_words
from ..text.tokenize import words
from .numbers import extract as extract_numbers
from .summarizer import is_noise, rank

_CLAIM_CUES = {
    "said": 1.1, "says": 1.1, "announced": 1.4, "confirmed": 1.5, "revealed": 1.4,
    "launched": 1.4, "released": 1.3, "unveiled": 1.4, "introduced": 1.2,
    "reported": 1.1, "added": 0.9, "noted": 0.9, "explained": 1.0, "stated": 1.1,
    "will": 1.15, "plans": 1.1, "expects": 1.1, "begins": 1.2, "starts": 1.2,
    "ships": 1.2, "available": 1.1, "costs": 1.3, "priced": 1.3, "raised": 1.2,
    "acquired": 1.4, "acquires": 1.4, "partners": 1.2, "partnered": 1.2,
    "increased": 1.1, "grew": 1.15, "declined": 1.1, "cut": 1.1, "hired": 1.0,
    "appointed": 1.2, "resigned": 1.2, "fined": 1.2, "sued": 1.2, "banned": 1.2,
    "approved": 1.2, "delayed": 1.2, "postponed": 1.2, "cancelled": 1.2,
}
_FILLER_STARTS = ("read more", "see also", "in this article", "as an ai", "note:",
                  "editor's note", "advertisement", "related:", "also read")
_DEFINITION = re.compile(r"\b(?:is|are|means|refers to|stands for|is defined as)\b", re.IGNORECASE)
_COMPARISON = re.compile(r"\b(?:than|vs\.?|versus|compared with|compared to|up from|down from)\b", re.IGNORECASE)


def extract(text: str, *, limit: int = 25, entity_names: list[str] | None = None) -> list:
    """Ranked facts with provenance. Returns a list of `types.Fact`."""
    from ..types import Fact

    entity_names = [name.lower() for name in (entity_names or [])]
    sentences = split_sentences(text)
    if not sentences:
        return []
    ranks = rank(sentences)
    numbers = {number.phrase().lower() for number in extract_numbers(text)}
    facts = []
    for index, sentence in enumerate(sentences):
        if is_noise(sentence) or sentence.lower().startswith(_FILLER_STARTS):
            continue
        tokens = words(sentence)
        if len(tokens) < 5:
            continue
        score = ranks[index] if index < len(ranks) else 0.0
        lowered = sentence.lower()
        score += sum(weight for cue, weight in _CLAIM_CUES.items() if re.search(rf"\b{cue}\b", lowered)) * 0.22
        sentence_numbers = sorted((phrase for phrase in numbers if phrase in lowered),
                                  key=lambda phrase: lowered.find(phrase))
        if sentence_numbers:
            score += 0.55 + 0.1 * len(sentence_numbers)
        if entity_names:
            hits = sum(1 for name in entity_names if name in lowered)
            score += 0.2 * hits
        if '"' in sentence or "“" in sentence:
            score += 0.3
        position_bonus = 1.0 / (1.0 + index * 0.35)
        score *= 0.75 + 0.5 * position_bonus
        length = word_count(sentence)
        if length > 45:
            score *= 0.85
        if '"' in sentence or "“" in sentence:
            kind = "quote"
        elif _COMPARISON.search(sentence):
            kind = "comparison"
        elif sentence_numbers:
            kind = "number"
        elif _DEFINITION.search(sentence) and length < 30:
            kind = "definition"
        else:
            kind = "statement"
        facts.append(Fact(text=sentence.strip(), score=round(min(2.0, score), 4), kind=kind,
                          entities=tuple(name for name in entity_names if name in lowered)[:4],
                          numbers=tuple(sentence_numbers[:5]),
                          sentence_index=index, words=length))
    facts.sort(key=lambda fact: (-fact.score, fact.sentence_index))
    return facts[:limit]


def dedupe_facts(facts: list) -> list:
    """Drop facts that restate an earlier one (Jaccard over content words)."""
    kept = []
    for fact in facts:
        tokens = set(content_words(words(fact.text)))
        if any(len(tokens & other) / max(1, len(tokens | other)) > 0.62 for other in kept):
            continue
        kept.append(tokens)
        facts[kept.index(tokens)] = fact
    return [fact for i, fact in enumerate(facts) if i < len(kept)]


def numeric_facts(facts: list) -> list:
    return [fact for fact in facts if fact.kind == "number"]


def claims_about(facts: list, entity: str) -> list:
    lowered = entity.lower()
    return [fact for fact in facts if lowered in fact.text.lower()]


def timeline(facts: list) -> list[str]:
    """Facts containing dates/relative time, in source order — for 'what happens next'."""
    from .numbers import relative_dates

    out = []
    for fact in sorted(facts, key=lambda item: item.sentence_index):
        if relative_dates(fact.text) or re.search(r"\b(?:20\d\d|january|february|march|april|may|june|"
                                                   r"july|august|september|october|november|december)\b",
                                                   fact.text, re.IGNORECASE):
            out.append(fact.text)
    return out
