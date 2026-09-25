"""Discourse transitions: glue between sentences and paragraphs.

Machine copy reads badly when every sentence starts cold. This picks a connector
from the actual rhetorical relation between two sentences (contrast, cause,
addition, evidence, time) and rotates variants so the same word is not repeated.
"""

import re
from collections import defaultdict

from ..lexicon import loader
from ..semantic.coherence import transition_needed

_state: dict[str, int] = defaultdict(int)


def reset() -> None:
    """Clear the rotation state — call at the start of every article."""
    _state.clear()


def options(relation: str) -> list[str]:
    return loader.transitions().get(relation, []) or ["Also"]


def pick(relation: str, *, avoid: set[str] | None = None) -> str:
    """Next unused connector for a relation, rotating to avoid repetition."""
    avoid = avoid or set()
    candidates = [option for option in options(relation) if option not in avoid]
    if not candidates:
        candidates = options(relation)
    index = _state[relation] % len(candidates)
    _state[relation] += 1
    return candidates[index]


_LOWERCASE_OPENERS = frozenset([
    "the", "a", "an", "this", "that", "these", "those", "it", "its", "they", "their",
    "he", "his", "she", "her", "we", "our", "you", "your", "there", "both", "each",
    "all", "some", "many", "most", "several", "such", "which", "who", "what", "when",
    "where", "why", "how", "because", "since", "while", "although", "after", "before",
])


def join(previous: str, following: str, *, force: str = "") -> str:
    """Prefix ``following`` with an appropriate connector (empty when none is needed)."""
    if not previous or not following:
        return following
    relation = force or transition_needed(previous, following)
    if relation == "sequence":
        return following
    head = following.split(" ", 1)[0].strip(".,;:")
    if head.lower() in {"however", "according", "but", "also", "meanwhile", "therefore", "still",
                        "yet", "separately", "notably", "in addition", "instead"}:
        return following                     # already connected
    connector = pick(relation)
    # Keep the whole sentence: the connector goes in front, the subject stays put.
    # Never lowercase an acronym or proper noun ("AMD responded" not "aMD").
    rest = following
    first_word = re.match(r"[A-Za-z][\w'\-\.]*", rest)
    if first_word and first_word.group(0).lower() in _LOWERCASE_OPENERS:
        # Only ordinary openers are lowercased; "Nvidia" and "AMD" must stay as they are.
        rest = first_word.group(0).lower() + rest[first_word.end():]
    return f"{connector}, {rest}"


def paragraph_opener(index: int, relation: str = "addition") -> str:
    """Opening connector for a new paragraph, varying by position."""
    if index == 0:
        return ""
    table = {1: "The details matter.", 2: "Beyond the headline numbers,",
             3: "There is more context.", 4: "Separately,"}
    return table.get(index, pick(relation) + ",")


def used() -> dict[str, int]:
    return dict(_state)


def variety_score(text: str) -> float:
    """Share of distinct sentence openers — a repetition guard (0..1, higher is better)."""
    sentences = [part.strip() for part in text.replace("!", ".").replace("?", ".").split(".") if part.strip()]
    if len(sentences) < 2:
        return 1.0
    openers = [sentence.split()[0].lower() for sentence in sentences if sentence.split()]
    distinct = len(set(openers))
    return round(distinct / len(openers), 3)


def repeated_openers(text: str, *, limit: int = 2) -> list[str]:
    """Openers used more than ``limit`` times — the writer must vary them."""
    counts: dict[str, int] = defaultdict(int)
    for sentence in [part.strip() for part in text.split(".") if part.strip()]:
        tokens = sentence.split()
        if tokens:
            counts[tokens[0].lower()] += 1
    return sorted(word for word, count in counts.items() if count > limit)
