"""Deterministic paraphrasing — rewriting without a language model.

Four reversible transformations, each guarded so meaning cannot drift:
1. lexical substitution from the bundled synonym lexicon (content words only);
2. voice and framing changes ("X announced Y" -> "Y was announced by X" is avoided;
   instead attribution moves to the front, which reads better in news);
3. clause reordering for subordinate clauses;
4. number/unit restatement ("3.5x faster" -> "an increase of 3.5 times").

Every rewrite is verified: if the content-word cosine to the original drops below
the preservation threshold, the original is kept. That is what makes this safe to
run on live publishing.
"""

import random
import re
from dataclasses import dataclass

from ..lexicon import loader
from ..semantic.similarity import cosine_lists
from ..text.stopwords import content_words, is_stopword
from ..text.tokenize import words

_PRESERVATION = 0.62
_QUOTE = re.compile(r'"[^"]+"|“[^”]+”')
_CLAUSE_SPLIT = re.compile(r",\s+(?=(?:which|while|after|before|because|although|as|so|and)\b)")
_NUMBER_RESTATE = (
    (re.compile(r"\b(\d+(?:\.\d+)?)\s?x faster\b", re.IGNORECASE), r"\1 times faster"),
    (re.compile(r"\b(\d+(?:\.\d+)?)\s?times faster\b", re.IGNORECASE), r"a \1x speed gain"),
    (re.compile(r"\bby (\d+(?:\.\d+)?)%\b"), r"by \1 percent"),
    (re.compile(r"\b(\d+(?:\.\d+)?)% higher\b"), r"higher by \1 percent"),
    (re.compile(r"\bdoubled\b"), r"increased twofold"),
    (re.compile(r"\btripled\b"), r"increased threefold"),
)


@dataclass
class ParaphraseResult:
    text: str
    changed: bool
    similarity: float
    substitutions: list[str]
    transformations: list[str]


def _synonym(word: str, rng: random.Random) -> str | None:
    options = loader.synonyms().get(word.lower())
    if not options:
        return None
    choice = rng.choice(options)
    if choice.lower() == word.lower():
        return None
    if word.isupper():
        return choice.upper()
    if word[:1].isupper():
        return choice[:1].upper() + choice[1:]
    return choice


_EDGE_PUNCT = ".,;:!?\"'()"
_COMPOUNDS: set[str] | None = None


def protected_compounds() -> set[str]:
    """Multi-word terms whose parts must not be substituted independently."""
    global _COMPOUNDS
    if _COMPOUNDS is None:
        compounds = {str(term).lower() for term in loader.tech_terms() if " " in str(term)}
        for name, entry in loader.gazetteer_entries().items():
            if " " in name:
                compounds.add(name.lower())
            compounds.update(str(alias).lower() for alias in entry.get("aliases", []) if " " in str(alias))
        compounds.update(place.lower() for place in loader.place_names() if " " in place)
        _COMPOUNDS = compounds
    return _COMPOUNDS


def locked_terms(text: str = "") -> set[str]:
    """Words that must never be swapped: proper nouns, brands, tech terms, units.

    Swapping "data" in "data centre" or "Cloud" in "Oracle Cloud" silently changes
    the meaning of a fact, so every capitalised token, gazetteer entry, bundled
    technical term and number is locked before any substitution runs.
    """
    locked = {term.lower() for term in loader.tech_terms()}
    for name, entry in loader.gazetteer_entries().items():
        locked.add(name.lower())
        locked.update(str(alias).lower() for alias in entry.get("aliases", []))
    for place in loader.place_names():
        locked.add(place.lower())
    for token in re.findall(r"\b[A-Z][A-Za-z0-9'\-\.]*\b", text):
        locked.add(token.lower())
    for token in re.findall(r"\b\d[\w\.%$/€£৳\-]*", text):
        locked.add(token.lower())
    for term in loader.tech_terms():
        for part in str(term).lower().split():
            if len(part) > 3:
                locked.add(part)
    # Second word of a capitalised pair is part of the name ("Oracle Cloud").
    for first, second in re.findall(r"\b([A-Z][\w\-]*)\s+([A-Za-z][\w\-]*)\b", text):
        if first.lower() in locked:
            locked.add(second.lower())
    return locked


def substitute(text: str, *, rate: float = 0.35, seed: int = 3, protect_quotes: bool = True,
               protect_names: bool = True) -> tuple[str, list[str]]:
    """Replace a bounded share of content words with lexicon synonyms."""
    rng = random.Random(seed)
    quoted: list[str] = []
    locked = locked_terms(text) if protect_names else set()

    def stash(match: re.Match[str]) -> str:
        quoted.append(match.group(0))
        return f"\x01{len(quoted) - 1}\x01"

    guarded = _QUOTE.sub(stash, text) if protect_quotes else text
    used: set[str] = set()
    changes: list[str] = []
    tokens = guarded.split(" ")
    candidates = [i for i, token in enumerate(tokens)
                  if token.strip(".,;:!?\"'()").lower() not in locked
                  and not is_stopword(token.strip(".,;:!?\"'()").lower())
                  and len(token.strip(".,;:!?\"'()")) > 3]
    rng.shuffle(candidates)
    compounds = protected_compounds()
    for index in list(candidates):
        # A word inside a known compound term is part of that term: swapping "data"
        # in "data centre" silently rewrites the fact.
        bare = tokens[index].strip(_EDGE_PUNCT).lower()
        before = tokens[index - 1].strip(_EDGE_PUNCT).lower() if index else ""
        after = (tokens[index + 1].strip(_EDGE_PUNCT).lower()
                 if index + 1 < len(tokens) else "")
        if f"{before} {bare}" in compounds or f"{bare} {after}" in compounds:
            candidates.remove(index)
    budget = max(1, int(len(candidates) * rate))
    for index in candidates[:budget]:
        raw = tokens[index]
        core = raw.strip(".,;:!?\"'()")
        prefix = raw[:len(raw) - len(raw.lstrip(".,;:!?\"'("))]
        suffix = raw[len(core) + len(prefix):]
        replacement = _synonym(core, rng)
        if not replacement or replacement.lower() in used:
            continue
        used.add(replacement.lower())
        tokens[index] = f"{prefix}{replacement}{suffix}"
        changes.append(f"{core} -> {replacement}")
    out = " ".join(tokens)
    if protect_quotes:
        out = re.sub(r"\x01(\d+)\x01", lambda m: quoted[int(m.group(1))], out)
    return out, changes


def restate_numbers(text: str) -> tuple[str, list[str]]:
    """Restate quantities in a different (equally accurate) form."""
    changes = []
    out = text
    for pattern, replacement in _NUMBER_RESTATE:
        new = pattern.sub(replacement, out)
        if new != out:
            changes.append("restated a quantity")
            out = new
    return out, changes


def reorder_clauses(text: str) -> tuple[str, list[str]]:
    """Move a trailing subordinate clause to the front when it reads better."""
    parts = [part.strip() for part in _CLAUSE_SPLIT.split(text) if part.strip()]
    if len(parts) < 2:
        return text, []
    tail = parts[-1]
    if len(tail.split()) > 14 or not re.match(r"^(?:which|while|after|before|because|although|as|so|and)\b",
                                              tail, re.IGNORECASE):
        return text, []
    connector = tail.split(" ", 1)[0]
    body = tail[len(connector):].strip()
    head = ", ".join(parts[:-1])
    if not body or not head:
        return text, []
    rewritten = f"{connector.capitalize()} {body}, {head[0].lower() + head[1:]}."
    return rewritten.rstrip(".") + ".", ["moved a subordinate clause to the front"]


_ROLE_PREFIX = re.compile(
    r"^(chief executive(?: officer)?|ceo|cfo|president|chairman|chairwoman|chair|"
    r"minister|prime minister|spokesperson|spokesman|spokeswoman|director|head of|"
    r"professor|dr|doctor|senator|governor|mayor|analyst|founder|co-founder)\s+",
    re.IGNORECASE)
_GENERIC_ACTOR = re.compile(
    r"(?:the|a|an)?\s*(?:company|firm|report|spokesperson|statement|document|paper|"
    r"study|team|group|outfit|maker|vendor|agency|organisation|organization|he|she|they|it|"
    r"chief executive|ceo|executive|official|source|analyst|blog|site|post)\.?", re.IGNORECASE)


def move_attribution(text: str) -> tuple[str, list[str]]:
    """'Apple said X' -> 'According to Apple, X' (varies attribution position)."""
    match = re.match(r"^([A-Z][\w'\-\. ]{1,40}?)\s+(said|says|announced|confirmed|reported|added|noted)\s+(?:that\s+)?(.+)$",
                     text.strip(), re.IGNORECASE)
    if not match:
        return text, []
    actor, verb, rest = match.group(1).strip(), match.group(2).lower(), match.group(3).strip()
    if _ROLE_PREFIX.match(actor):
        # "Chief executive Jensen Huang" -> "chief executive Jensen Huang": a job title
        # is not a proper noun, and capitalising it mid-sentence reads as a mistake.
        match_role = _ROLE_PREFIX.match(actor)
        actor = f"{match_role.group(1).lower()} {actor[match_role.end():]}"
    if _GENERIC_ACTOR.fullmatch(actor):
        # "The company said ..." carries no attribution value; fronting it produces
        # the ungrammatical "according to The company", so leave the sentence alone.
        return text, []
    if len(actor.split()) > 5 or rest[0].isupper() is False:
        rest = rest[0].upper() + rest[1:]
    if verb in {"said", "says", "told"}:
        return f"According to {actor}, {rest[0].lower() + rest[1:]}", ["fronted the attribution"]
    return f"{actor} {verb} that {rest[0].lower() + rest[1:]}", ["kept attribution, added complementiser"]


def paraphrase(text: str, *, seed: int = 3, rate: float = 0.3,
               preserve_threshold: float = _PRESERVATION,
               allow_clause_reorder: bool = True) -> ParaphraseResult:
    """Full paraphrase pass with a meaning-preservation guard."""
    if not text.strip():
        return ParaphraseResult(text=text, changed=False, similarity=1.0,
                                substitutions=[], transformations=[])
    original_tokens = content_words(words(text))
    transformations: list[str] = []
    substitutions: list[str] = []
    out = text

    restated, changes = restate_numbers(out)
    if changes:
        out, transformations = restated, transformations + changes
    attributed, changes = move_attribution(out)
    if changes:
        out, transformations = attributed, transformations + changes
    if allow_clause_reorder:
        reordered, changes = reorder_clauses(out)
        if changes:
            out, transformations = reordered, transformations + changes
    replaced, changes = substitute(out, rate=rate, seed=seed)
    if changes:
        out, substitutions = replaced, changes
        transformations.append(f"{len(changes)} lexical substitution(s)")

    similarity = cosine_lists(original_tokens, content_words(words(out)))
    if similarity < preserve_threshold:
        return ParaphraseResult(text=text, changed=False, similarity=round(similarity, 4),
                                substitutions=[], transformations=["rejected: meaning drifted"])
    return ParaphraseResult(text=re.sub(r"\s+", " ", out).strip(), changed=out != text,
                            similarity=round(similarity, 4), substitutions=substitutions,
                            transformations=transformations)


def unique_against(text: str, existing: list[str], *, seed: int = 5,
                   threshold: float = 0.82) -> tuple[str, list[str]]:
    """Keep paraphrasing (with new seeds) until the text is distinct enough."""
    attempts: list[str] = []
    current = text
    for attempt in range(4):
        best = max((cosine_lists(content_words(words(current)), content_words(words(other)))
                    for other in existing), default=0.0)
        if best < threshold:
            return current, attempts
        result = paraphrase(current, seed=seed + attempt * 7, rate=0.25 + attempt * 0.1)
        attempts.append(f"attempt {attempt + 1}: similarity {best:.2f} -> "
                        f"{result.similarity:.2f} ({len(result.substitutions)} swaps)")
        if result.changed:
            current = result.text
    return current, attempts


def is_verbatim(sentence: str, source: str, *, threshold: float = 0.9) -> bool:
    """True when a generated sentence is a near copy of a source sentence."""
    return max((cosine_lists(content_words(words(sentence)), content_words(words(other)))
                for other in source.split(". ") if other.strip()), default=0.0) >= threshold
