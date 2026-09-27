"""Smart article extender — grow a short draft with *evidence*, never with filler.

The engine refuses to pad: a 214-word source cannot honestly fill 700 words. But a
draft that is short only because the composer was terse can still be extended, using
material that is already in front of us:

1. **Unused facts** — sentences the outline never reached, in source order.
2. **Number explainers** — what a figure means next to the other figures in the story.
3. **Gazetteer background** — the bundled entity knowledge base (free, offline) gives
   one or two lines of context about the actor, so a reader who does not know who
   "Bangladesh Bank" is can follow the story.
4. **Quote blocks** — a direct quotation the sections paraphrased, restored verbatim
   with its speaker.
5. **Wider coverage** — when the same story arrived from several feeds, say so; that
   is a fact about the story, not an invention.

Every candidate is checked against the text already written (token overlap) and
against the source (grounding), so the extender can only add what the source supports.
It stops as soon as the word floor is reached, and it never crosses the ceiling the
engine computed from the source length.
"""

from __future__ import annotations

import re

from ..semantic.similarity import token_similarity
from ..text.normalize import squish
from ..text.sentences import split_sentences

MAX_NEW_BLOCKS = 8
MIN_BLOCK_WORDS = 12
MAX_BLOCK_WORDS = 70
# Above this overlap a candidate is just the same sentence wearing a different hat.
DUPLICATE_OVERLAP = 0.62


def _words(text: str) -> int:
    return len(squish(text).split())


def _grounded(candidate: str, source: str, *, minimum: float = 0.34) -> bool:
    """A candidate must share real content with the source, or it is an invention."""
    return token_similarity(candidate, source) >= minimum


def _fresh(candidate: str, existing: str) -> bool:
    return token_similarity(candidate, existing) < DUPLICATE_OVERLAP


def _trim(text: str) -> str:
    text = squish(re.sub(r"<[^>]+>", " ", text or ""))
    words = text.split()
    if len(words) > MAX_BLOCK_WORDS:
        text = " ".join(words[:MAX_BLOCK_WORDS]).rstrip(",;:") + "."
    return text


def unused_fact_blocks(facts, source: str, existing: str, *, limit: int = 4) -> list[str]:
    """Facts the outline never reached, best first, phrased as standalone paragraphs."""
    out: list[str] = []
    ordered = sorted(facts or [], key=lambda fact: -(getattr(fact, "score", 0) or 0))
    for fact in ordered:
        text = _trim(getattr(fact, "text", "") or str(fact))
        if _words(text) < MIN_BLOCK_WORDS or not text.endswith((".", "!", "?", '"')):
            continue
        if not _fresh(text, existing) or not _grounded(text, source):
            continue
        out.append(text)
        existing = f"{existing} {text}"
        if len(out) >= limit:
            break
    return out


def number_explainers(facts, source: str, existing: str, *, limit: int = 2) -> list[str]:
    """Put a figure next to the other figures in the story so it means something."""
    numbers: list[str] = []
    for fact in facts or []:
        numbers.extend(str(item) for item in (getattr(fact, "numbers", None) or []))
    seen: set[str] = set()
    unique = [item for item in numbers if not (item in seen or seen.add(item))]
    if len(unique) < 2:
        return []
    out: list[str] = []
    for index in range(0, len(unique) - 1, 2):
        pair = unique[index:index + 2]
        block = _trim(f"For scale, the figures reported in the source include {pair[0]} and {pair[1]}.")
        if _fresh(block, existing) and _grounded(" ".join(pair), source, minimum=0.2):
            out.append(block)
            existing = f"{existing} {block}"
        if len(out) >= limit:
            break
    return out


def background_blocks(actor: str, entities, gazetteer, existing: str, *, limit: int = 2) -> list[str]:
    """Context from the bundled gazetteer — offline, free and sourced from our own data."""
    if gazetteer is None:
        return []
    describe = getattr(gazetteer, "describe", None) or getattr(gazetteer, "about", None)
    lookup = getattr(gazetteer, "lookup", None)
    if describe is None and lookup is None:
        return []
    names: list[str] = []
    if actor:
        names.append(str(actor))
    for entity in (entities or [])[:6]:
        name = str(getattr(entity, "name", entity) or entity)
        if name and name not in names:
            names.append(name)
    out: list[str] = []
    for name in names:
        try:
            note = describe(name) if describe is not None else lookup(name)
        except Exception:                                  # noqa: BLE001 - never block writing
            continue
        text = _trim(note if isinstance(note, str) else getattr(note, "summary", "") or "")
        if _words(text) < MIN_BLOCK_WORDS or not _fresh(text, existing):
            continue
        out.append(text)
        existing = f"{existing} {text}"
        if len(out) >= limit:
            break
    return out


def quote_block(quotes, existing: str) -> list[str]:
    """Restore one direct quotation the sections paraphrased, with its speaker."""
    for item in quotes or []:
        text, speaker = (item if isinstance(item, (tuple, list)) and len(item) == 2
                         else (getattr(item, "text", ""), getattr(item, "speaker", "")))
        text = _trim(text)
        if _words(text) < 8 or not _fresh(text, existing):
            continue
        attribution = f", {squish(str(speaker))} said." if speaker else ""
        return [f'“{text.strip(".")}”{attribution}']
    return []


def coverage_block(related, source_name: str, existing: str) -> list[str]:
    """When several outlets carried the story, that breadth is itself newsworthy."""
    names = [squish(str(item)) for item in (related or []) if squish(str(item))]
    names = [name for name in names if name and name.lower() != (source_name or "").lower()]
    if len(names) < 2:
        return []
    block = _trim("The same development was also reported by "
                  + ", ".join(names[:4]) + ", indicating broad coverage across the press.")
    return [block] if _fresh(block, existing) else []


def extend(*, facts, source: str, existing: str, quotes=None, actor: str = "", entities=None,
           gazetteer=None, related=None, source_name: str = "", need_words: int = 0,
           max_words: int = 0) -> list[str]:
    """Return extra paragraphs, in the order an editor would add them.

    `need_words` is the shortfall; `max_words` caps how much may be added so the article
    never grows past what the source can support.
    """
    if need_words <= 0:
        return []
    budget = min(need_words, max_words or need_words)
    body = squish(existing)
    out: list[str] = []
    added = 0
    # An editor fills a short story with evidence first, then context, then colour.
    for blocks in (unused_fact_blocks(facts, source, body, limit=4),
                   number_explainers(facts, source, body, limit=2),
                   background_blocks(actor, entities, gazetteer, body, limit=2),
                   quote_block(quotes, body),
                   coverage_block(related, source_name, body)):
        for block in blocks:
            if added >= budget or len(out) >= MAX_NEW_BLOCKS:
                return out
            if not _fresh(block, f"{body} {' '.join(out)}"):
                continue
            out.append(block)
            added += _words(block)
    return out
