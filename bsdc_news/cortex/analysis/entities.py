"""Named-entity recognition without a model: gazetteer + pattern + statistics.

Three signals are fused:
* a curated gazetteer of companies, products, people and places (exact, fast);
* morphological patterns (capitalised runs, "CEO of X", "Mr X", acronym + expansion);
* statistical salience (frequency x position x capitalisation).
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from ..text.tokenize import words

ORG_SUFFIXES = {"inc", "ltd", "llc", "corp", "corporation", "company", "co", "group",
                "holdings", "technologies", "technology", "labs", "lab", "institute",
                "university", "college", "foundation", "commission", "committee",
                "department", "ministry", "agency", "authority", "bank", "airlines",
                "motors", "media", "studios", "pictures", "networks", "systems",
                "solutions", "partners", "capital", "ventures", "industries",
                "research", "analytics", "communications", "communication", "telecom",
                "semiconductor", "semiconductors", "electronics", "energy", "power",
                "pharma", "pharmaceuticals", "biotech", "health", "hospital", "school",
                "association", "council", "bureau", "service", "services", "works",
                "shipping", "logistics", "retail", "foods", "chemical", "aerospace"}
ROLE_WORDS = {"ceo", "cfo", "cto", "coo", "cio", "president", "chairman", "chairwoman",
              "founder", "co-founder", "chief", "officer", "director", "manager",
              "head", "lead", "executive", "vp", "minister", "senator", "mayor",
              "governor", "president-elect", "spokesperson", "analyst", "professor",
              "researcher", "engineer", "designer", "developer"}
HONORIFICS = {"mr", "mrs", "ms", "dr", "prof", "professor", "sir", "dame", "sen",
              "rep", "gov", "senator", "minister", "capt", "gen", "col"}
PLACE_HINTS = {"city", "country", "state", "region", "capital", "island", "county"}
_TEMPORAL_NAMES = frozenset([
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "today", "tomorrow",
    "yesterday", "tonight", "weekend", "christmas", "eid", "new year",
])

# Two to five capitalised words, whitespace separated: never crosses a full stop.
_CAPITALISED_RUN = re.compile(r"\b[A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){1,4}")
_ACRONYM_EXPANSION = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})\s+\(([A-Z]{2,6})\)")
_QUOTED = re.compile(r'"([^"]{3,60})"')


@dataclass
class Entity:
    text: str
    kind: str            # ORG | PERSON | PRODUCT | PLACE | EVENT | MISC
    count: int = 1
    score: float = 0.0
    first_position: float = 1.0
    aliases: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return self.text.lower()


class Gazetteer:
    """Case-insensitive multi-word gazetteer with alias resolution."""

    def __init__(self, entries: dict[str, tuple[str, tuple[str, ...]]] | None = None) -> None:
        self.entries: dict[str, tuple[str, tuple[str, ...]]] = entries or {}
        self._index: dict[str, str] = {}
        for canonical, (_kind, aliases) in self.entries.items():
            for surface in (canonical, *aliases):
                self._index[surface.lower()] = canonical

    def add(self, canonical: str, kind: str = "ORG", aliases: tuple[str, ...] = ()) -> None:
        self.entries[canonical] = (kind, aliases)
        for surface in (canonical, *aliases):
            self._index[surface.lower()] = canonical

    def lookup(self, surface: str) -> tuple[str, str] | None:
        canonical = self._index.get(surface.lower())
        if canonical is None:
            return None
        return canonical, self.entries[canonical][0]

    def find(self, text: str) -> Counter:
        """Count gazetteer hits, longest surface form first, on word boundaries.

        Substring matching invents entities that are not in the article: "ces" inside
        "process", "su" inside "consumer", "us" inside "Huang". Every surface form is
        therefore matched with non-word lookarounds.
        """
        found: Counter = Counter()
        remaining = text
        lowered = text.lower()
        for surface in sorted(self._index, key=len, reverse=True):
            if not surface or surface not in lowered:
                continue
            pattern = re.compile(rf"(?<![\w'\-]){re.escape(surface)}(?![\w'\-])", re.IGNORECASE)
            hits = len(pattern.findall(remaining))
            if not hits:
                continue
            found[self._index[surface]] += hits
            remaining = pattern.sub(lambda match: " " * len(match.group(0)), remaining)
        return found


def acronym_pairs(text: str) -> dict[str, str]:
    """Map acronym -> expansion for patterns like 'Artificial Intelligence (AI)'."""
    return {match.group(2): match.group(1) for match in _ACRONYM_EXPANSION.finditer(text)}


def capitalised_runs(text: str) -> list[str]:
    """Multi-word capitalised spans — the raw material of PERSON/ORG detection."""
    out = []
    for match in _CAPITALISED_RUN.finditer(text):
        span = match.group(0).strip(" .,;:")
        tokens = span.split()
        if len(tokens) < 2 or all(token.isupper() for token in tokens):
            continue
        out.append(span)
    return out


def classify(span: str, kind_hint: str = "", context: str = "") -> str:
    """Guess the entity type of a capitalised span."""
    if kind_hint:
        return kind_hint
    tokens = [token.strip(".").lower() for token in span.split()]
    if tokens[-1] in ORG_SUFFIXES:
        return "ORG"
    if tokens[0] in HONORIFICS:
        return "PERSON"
    if context and span in context:
        start = context.find(span)
        before = context[max(0, start - 45):start].lower()
        # Only the two or three words immediately before the span are evidence:
        # a role word further back belongs to a different mention.
        tail = [word.strip(",.;:") for word in before.split()][-3:]
        if any(word in ROLE_WORDS | HONORIFICS for word in tail):
            return "PERSON"
        if before.rstrip().endswith((" at", " in", " from", " by", " with", " of", "across")):
            return "ORG"
        # "said Alan Chen, a semiconductor analyst at Meridian Research": the role
        # follows the name, so look forward as well as back.
        after = context[start + len(span): start + len(span) + 70].lower()
        following = [word.strip(",.;:") for word in after.split()][:8]
        if any(word in ROLE_WORDS for word in following):
            return "PERSON"
    if len(tokens) == 1 and tokens[0].isupper() and len(tokens[0]) > 2:
        return "ORG"          # an ALL-CAPS token is almost always a brand
    # A two-word capitalised span is NOT assumed to be a person: without a name
    # list that mislabels products ("Rubin Ultra"). The gazetteer decides those.
    return "MISC"


def roles(text: str) -> list[tuple[str, str]]:
    """Extract (person, role) pairs from patterns like 'CEO Jensen Huang'."""
    out = []
    for match in re.finditer(
        r"\b(?P<role>" + "|".join(sorted(ROLE_WORDS, key=len, reverse=True)) + r")\s+"
        r"(?P<name>[A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+){0,3})", text, re.IGNORECASE):
        out.append((match.group("name").strip(), match.group("role").lower()))
    for match in re.finditer(
        r"\b(?P<name>[A-Z][\w'\-]+(?:\s+[A-Z][\w'\-]+){0,3}),?\s+(?:the\s+)?"
        r"(?P<role>" + "|".join(sorted(ROLE_WORDS, key=len, reverse=True)) + r")\s+of\s+"
        r"(?P<org>[A-Z][\w'\-&\. ]{1,40})", text):
        out.append((match.group("name").strip(), f"{match.group('role').lower()} of {match.group('org').strip()}"))
    return out


def extract(text: str, *, gazetteer: Gazetteer | None = None, top: int = 25) -> list[Entity]:
    """All entities in a document, scored and deduplicated."""
    if not text:
        return []
    gazetteer = gazetteer or Gazetteer()
    counts = gazetteer.find(text)
    kinds = {canonical: gazetteer.entries[canonical][0] for canonical in counts}
    length = max(1, len(text))

    # Pattern-based candidates.
    for span in capitalised_runs(text):
        hit = gazetteer.lookup(span) if gazetteer.entries else None
        canonical, kind = hit if hit else (span, classify(span, context=text))
        counts[canonical] += 1
        kinds[canonical] = kinds.get(canonical) or kind

    # Single capitalised tokens that are not sentence-initial.
    for match in re.finditer(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,})\b", text, re.MULTILINE):
        token = match.group(1)
        hit = gazetteer.lookup(token) if gazetteer.entries else None
        canonical, kind = hit if hit else (token, classify(token, context=text))
        counts[canonical] += 1
        kinds[canonical] = kinds.get(canonical) or kind

    entities: list[Entity] = []
    # Snapshot the items: folding "The Rubin Ultra" into "Rubin Ultra" mutates counts.
    for canonical, count in list(counts.items()):
        if canonical.lower() in _TEMPORAL_NAMES:
            continue                     # "Monday" is a date, not a named entity
        first = text.find(canonical)
        if first < 0:
            # Never publish an entity the article does not contain.
            if canonical.lower() not in text.lower():
                continue
            first = text.lower().find(canonical.lower())
        if canonical.lower().startswith("the ") and len(canonical.split()) > 1:
            stripped = canonical[4:].strip()
            if stripped:
                counts[stripped] = counts.get(stripped, 0) + count
                kinds[stripped] = kinds.get(stripped) or kinds.get(canonical, "MISC")
                continue
        position = (first / length) if first >= 0 else 1.0
        word_count = max(1, len(words(canonical)))
        score = (
            2.2 * math.log1p(count)
            + 1.4 * (1.0 - position)                 # earlier = more important
            + 0.8 * min(1.0, word_count / 3)         # multi-word spans are specific
            + (1.0 if kinds.get(canonical) in {"ORG", "PERSON", "PRODUCT"} else 0.0)
        )
        entities.append(Entity(text=canonical, kind=kinds.get(canonical, "MISC"), count=count,
                               score=round(score, 4), first_position=round(position, 4)))
    entities.sort(key=lambda entity: (-entity.score, entity.text))
    # Merge a bare surname into a fuller mention ("Huang" into "Jensen Huang").
    merged: list[Entity] = []
    for entity in entities:
        target = next((other for other in merged
                       if other.text != entity.text and other.text.lower().endswith(entity.text.lower())
                       and len(other.text.split()) > len(entity.text.split())), None)
        if target:
            target.count += entity.count
            target.score = round(target.score + entity.score * 0.4, 4)
            target.aliases = tuple(sorted({*target.aliases, entity.text}))
            continue
        merged.append(entity)
    # A single word that is part of a longer mention already found ("Jensen" inside
    # "Jensen Huang", "San" inside "San Jose") is a fragment, not an entity.
    multiword = [entity.text.lower() for entity in merged if " " in entity.text]
    fragments = []
    for entity in merged:
        if " " in entity.text:
            continue
        lowered = entity.text.lower()
        if any(f" {lowered} " in f" {phrase} " or phrase.startswith(lowered + " ")
               or phrase.endswith(" " + lowered) for phrase in multiword):
            fragments.append(entity)
    for fragment in fragments:
        merged.remove(fragment)
    merged.sort(key=lambda entity: (-entity.score, entity.text))
    return merged[:top]


def by_kind(entities: list[Entity], kind: str) -> list[Entity]:
    return [entity for entity in entities if entity.kind == kind]


def names(entities: list[Entity], *, kinds: tuple[str, ...] = ()) -> list[str]:
    if kinds:
        return [entity.text for entity in entities if entity.kind in kinds]
    return [entity.text for entity in entities]


def quoted_phrases(text: str) -> list[str]:
    return [match.group(1).strip() for match in _QUOTED.finditer(text)]
