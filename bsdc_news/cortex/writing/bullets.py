"""Bullet lists: "at a glance", key numbers and spec tables from real facts.

Bullets are the highest-value real estate for featured snippets, so they are built
from numeric and definitional facts only, capped in length, and phrased in
parallel form (label first, value second).
"""

import re

from ..text import pos
from ..text.normalize import squish
from ..text.sentences import split_sentences
from ..types import Fact

MAX_BULLETS = 6
MAX_BULLET_WORDS = 20
_LABEL = re.compile(r"^\s*([A-Z][\w\s\-/]{1,32}?)\s*[:\-–]\s*(.+)$")


def key_numbers(facts: list[Fact], *, limit: int = MAX_BULLETS) -> list[str]:
    """Numeric facts as short, parallel bullets."""
    out: list[str] = []
    for fact in facts:
        if fact.kind != "number":
            continue
        for number in fact.numbers[:2]:
            label = _label_for(fact.text, number)
            text = f"{label}: {number}" if label else squish(fact.text)
            text = _clip(text)
            if text and text not in out:
                out.append(text)
        if len(out) >= limit:
            break
    return out[:limit]


def at_a_glance(facts: list[Fact], *, limit: int = 4) -> list[str]:
    """The four facts a skimmer needs, in plain language."""
    picks: list[str] = []
    for fact in facts:
        if fact.kind == "quote":
            continue
        text = _clip(squish(fact.text))
        if len(text.split()) < 4 or text in picks:
            continue
        picks.append(text)
        if len(picks) >= limit:
            break
    return picks


def specs(facts: list[Fact], *, limit: int = MAX_BULLETS) -> list[tuple[str, str]]:
    """(label, value) pairs suitable for a definition list or table."""
    rows: list[tuple[str, str]] = []
    for fact in facts:
        if not fact.numbers:
            continue
        label = _label_for(fact.text, fact.numbers[0])
        if not label:
            continue
        value = fact.numbers[0]
        if len(fact.numbers) > 1:
            value = ", ".join(fact.numbers[:3])
        if (label, value) not in rows:
            rows.append((label, value))
        if len(rows) >= limit:
            break
    return rows


def comparisons(facts: list[Fact], *, limit: int = 4) -> list[str]:
    """Facts that contain a comparison, as bullets."""
    out = []
    for fact in facts:
        if fact.kind != "comparison":
            continue
        text = _clip(squish(fact.text))
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


_LABEL_STOP = frozenset([
    "said", "says", "saying", "told", "added", "noted", "explained", "confirmed",
    "reported", "announced", "delivers", "deliver", "delivered", "estimated",
    "expects", "will", "would", "that", "which", "who", "of", "at", "by", "to",
    "from", "up", "down", "with", "for", "on", "in", "and", "or", "the", "a", "an",
    "its", "their", "his", "her", "it", "he", "she", "they", "was", "were", "is",
    "are", "be", "been", "about", "over", "nearly", "almost", "more", "less",
    "than", "per", "as", "year", "quarter", "month",
])
_UNIT_WORDS = frozenset([
    "million", "billion", "thousand", "trillion", "percent", "times", "dollars",
    "euros", "pounds", "taka", "terabytes", "gigabytes", "megabytes", "watts",
    "kilowatts", "metres", "meters", "kilometres", "miles", "hours", "minutes",
    "seconds", "days", "weeks", "months", "years", "units", "people", "users",
])
_VERB_FORMS = frozenset([
    "delivers", "delivered", "deliver", "reaches", "reached", "spend", "spends",
    "priced", "prices", "costs", "cost", "rose", "fell", "grew", "increased",
    "decreased", "holds", "holding", "moves", "moved", "ships", "ship", "shipped",
    "said", "told", "added", "noted", "estimated", "estimates", "expects",
    "reported", "announced", "confirmed", "unveiled", "unveils", "launches",
    "launched", "released", "releases", "sells", "sold", "paid", "raised", "raises",
    "cut", "cuts", "hired", "opened", "opens", "expands", "expanded", "begins",
    "starts", "ends", "plans", "planned", "promises", "promised", "seeks", "wants",
    "needs", "uses", "used", "makes", "made", "builds", "built", "offers",
    "offered", "includes", "included", "supports", "supported", "enables",
    "enabled", "provides", "provided", "leads", "led", "runs", "ran", "works",
    "produces", "produced", "earns", "earned", "loses", "lost", "gains", "gained",
])
_KIND_LABEL = {"money": "Price", "percent": "Change", "date": "Timing",
               "measure": "Specification", "multiplier": "Gain", "count": "Count",
               "range": "Range", "quantity": "Figure"}


def _label_for(text: str, number: str) -> str:
    """A noun-phrase label for a figure, found with the POS tagger.

    The word before a number is often a verb ("delivers 3.5 times"), so the label is
    taken from the nearest noun — before the figure if there is one, otherwise after
    it ("3.5 times the inference throughput" -> "inference throughput").
    """
    match = _LABEL.match(text)
    if match and not _verb_like(match.group(1)):
        return match.group(1).strip()
    index = text.find(number)
    if index < 0:
        return ""
    head = text[:index].strip().rstrip(",;:")
    tail = text[index + len(number):].strip().lstrip(",;:")
    # "delivers 3.5 times the inference throughput": the word before the figure is a
    # verb, so the real label lives after it.
    chunks = (tail, head) if _ends_with_verb(head) else (head, tail)
    for chunk in chunks:
        label = _noun_label(chunk, reverse=(chunk is head))
        if label:
            return label
    return ""


def _ends_with_verb(chunk: str) -> bool:
    tokens = re.findall(r"[A-Za-z][\w'\-]*", chunk)[-2:]
    if not tokens:
        return False
    return any(item.tag.startswith("VB") for item in pos.tag(tokens))


def _noun_label(chunk: str, *, reverse: bool = False) -> str:
    """Nearest noun phrase in a chunk, stopping at the first verb.

    Scanning "Jensen Huang said the platform delivers" backwards must stop at
    "delivers": otherwise the label becomes the person's name.
    """
    tokens = re.findall(r"[A-Za-z][\w'\-]*", chunk)
    if not tokens:
        return ""
    tagged = pos.tag(tokens)
    items = list(reversed(tagged)) if reverse else list(tagged)
    picks: list[str] = []
    for item in items:
        word = item.token
        lowered = word.lower()
        if item.tag.startswith("VB") or lowered in _VERB_FORMS:
            # The figure is this verb's object, so nothing before the verb describes it.
            break
        if lowered in _LABEL_STOP or lowered in _UNIT_WORDS or len(word) < 3:
            continue
        if not item.tag.startswith("NN"):
            if picks:
                break
            continue
        picks.append(word)
        if len(picks) >= 2:
            break
    if not picks:
        return ""
    if reverse:
        picks.reverse()
    label = " ".join(picks).strip(".,;: ")
    if _verb_like(label):
        return ""
    return label[0].upper() + label[1:]


def _verb_like(phrase: str) -> bool:
    """Reject labels that are really verb phrases ("said the platform delivers")."""
    tokens = [token.lower().strip(".,;:") for token in phrase.split()]
    if not tokens:
        return True
    if any(token in _LABEL_STOP or token.endswith(("ing", "ed")) for token in tokens):
        return True
    return len(tokens) > 4


def label_from_number(number, *, source: str = "", fallback: str = "") -> str:
    """Label a `numbers.Number` from its own sentence, else from its kind."""
    phrase = number.phrase() if callable(getattr(number, "phrase", None)) else str(number)
    sentence = _sentence_of(source, phrase, getattr(number, "position", 0.5))
    if sentence:
        label = _label_for(sentence, phrase)
        if label:
            return label
    kind = str(getattr(number, "kind", "") or "")
    if kind in _KIND_LABEL:
        return _KIND_LABEL[kind]
    unit = str(getattr(number, "unit", "") or "").strip()
    return unit.title() if unit else fallback


def _sentence_of(source: str, phrase: str, position: float) -> str:
    """The sentence containing a figure, located by text match or relative position."""
    if not source:
        return ""
    sentences = split_sentences(source)
    if not sentences:
        return ""
    for sentence in sentences:
        if phrase and phrase in sentence:
            return sentence
    index = min(len(sentences) - 1, max(0, int(float(position) * len(sentences))))
    return sentences[index]


def specs_from_numbers(numbers: list, *, source: str = "",
                       limit: int = MAX_BULLETS) -> list[tuple[str, str]]:
    """(label, value) rows built from parsed numbers rather than raw sentences."""
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for number in numbers:
        phrase = number.phrase() if callable(getattr(number, "phrase", None)) else str(number)
        if not phrase or phrase in seen:
            continue
        label = label_from_number(number, source=source)
        if not label:
            continue
        seen.add(phrase)
        rows.append((label, phrase))
        if len(rows) >= limit:
            break
    return rows


_DANGLING = frozenset(["and", "or", "but", "while", "which", "that", "who", "of", "to",
                       "in", "for", "with", "on", "at", "by", "from", "as", "a", "an",
                       "the", "its", "their", "his", "her", "it", "than", "per", "up"])


def _clip(text: str) -> str:
    """Trim to bullet length without leaving a dangling conjunction or preposition."""
    text = squish(text).strip("-–—: ")
    words = text.split()
    if len(words) > MAX_BULLET_WORDS:
        window = " ".join(words[:MAX_BULLET_WORDS])
        cut_at = -1
        for boundary in (", ", "; ", " and ", " which ", " that "):
            position = window.rfind(boundary)
            if position > cut_at and position > len(window) * 0.4:
                cut_at = position
        text = window[:cut_at].strip() if cut_at > 0 else window.rstrip(",;:")
    words = text.split()
    while words and words[-1].lower().strip(".,;:") in _DANGLING:
        words.pop()
    text = " ".join(words).rstrip(",;: ")
    if not text:
        return ""
    return text if text.endswith((".", "!", "?", "%")) else text + "."
