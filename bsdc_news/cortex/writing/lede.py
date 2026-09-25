"""Lede (opening paragraph) generation.

The lede carries who, what, when and where in one or two sentences. It is built
from the top-ranked facts and then checked so it does not repeat the headline
word for word — a duplicated lede wastes the most valuable paragraph on the page.
"""

import re

from ..semantic.similarity import token_similarity
from ..text.normalize import squish
from ..text.sentences import split_sentences
from ..types import Fact

_MAX_LEDE_WORDS = 42
_WHO = re.compile(r"\b([A-Z][\w&\.\-']+(?:\s+[A-Z][\w&\.\-']+)*)\b")


def angles(facts: list[Fact], limit: int = 3) -> list[Fact]:
    """Facts that answer who/what first; definitional and numeric facts lead."""
    priority = {"statement": 0, "definition": 1, "number": 2, "comparison": 3, "quote": 4}
    return sorted(facts[: limit * 2], key=lambda fact: (priority.get(fact.kind, 5), -fact.score))[:limit]


def build(facts: list[Fact], *, headline: str = "", entities: list[str] | None = None,
          actor: str = "", when: str = "", where: str = "", max_similarity: float = 0.72) -> str:
    """Compose the opening paragraph from real facts."""
    entities = entities or []
    picked = angles(facts, limit=3)
    if not picked:
        return ""
    sentences = [squish(fact.text) for fact in picked]
    sentences = list(dict.fromkeys(sentences))
    lede = sentences[0]
    words = lede.split()
    if len(words) > _MAX_LEDE_WORDS:
        lede = " ".join(words[:_MAX_LEDE_WORDS]).rstrip(",;:") + "."
    for extra in sentences[1:]:
        if len((lede + " " + extra).split()) > _MAX_LEDE_WORDS + 18:
            break
        if token_similarity(lede, extra) > 0.55:
            continue
        lede = f"{lede.rstrip('.')} {extra}" if extra[0].islower() else f"{lede.rstrip('.')}. {extra}"
    if headline and token_similarity(lede, headline) > max_similarity:
        lede = _differentiate(lede, headline, entities, actor)
    if when and when.lower() not in lede.lower() and len(lede.split()) < 30:
        lede = lede.rstrip(".") + f", {when.lower()}."
    if where and where.lower() not in lede.lower() and len(lede.split()) < 30:
        lede = lede.rstrip(".") + f" in {where}."
    return squish(lede)


def _differentiate(lede: str, headline: str, entities: list[str], actor: str) -> str:
    """Rephrase the lede so it complements the headline instead of echoing it."""
    subject = actor or (entities[0] if entities else "")
    pieces = split_sentences(lede)
    if len(pieces) > 1 and token_similarity(pieces[1], headline) <= 0.7:
        return squish(pieces[1]) if len(pieces[1].split()) >= 8 else squish(pieces[0])
    if subject and lede.lower().startswith(subject.lower()):
        rest = lede[len(subject):].lstrip(" ,")
        if rest and len(rest.split()) >= 6:
            return squish(f"{rest[0].upper()}{rest[1:]} The {subject.lower()} confirmed the details.")
    return squish(lede)


def second_paragraph(facts: list[Fact], *, used: set[str], limit: int = 2) -> str:
    """The nut-graf: what the reader needs next, from facts not already used."""
    picks = [fact for fact in facts if fact.text not in used and fact.kind != "quote"][:limit]
    if not picks:
        return ""
    return squish(" ".join(squish(fact.text) for fact in picks))


def summary_dek(facts: list[Fact], *, lede: str, max_words: int = 26) -> str:
    """A one-sentence standfirst for social cards, distinct from the lede."""
    for fact in facts:
        text = squish(fact.text)
        if token_similarity(text, lede) > 0.6:
            continue
        if fact.kind == "quote" or text[:1] in "\"'“":
            continue          # a standfirst that opens on a quote reads like a pull-quote
        words = text.split()
        if len(words) < 5:
            continue
        if len(words) > max_words:
            text = " ".join(words[:max_words]).rstrip(",;:") + "."
        return text
    for fact in facts:                     # nothing suitable: fall back to any fact
        text = squish(fact.text)
        if token_similarity(text, lede) > 0.6 or len(text.split()) < 5:
            continue
        return text
    return squish(lede)[:180]
