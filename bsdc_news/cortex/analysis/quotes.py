"""Quotation detection, cleaning and attribution.

Direct quotes are the highest-trust content in news, so they are extracted with
their speaker, kept verbatim, and never paraphrased by the rewriter.
"""

import re
from dataclasses import dataclass

from ..text.normalize import squish
from ..text.sentences import split_sentences

_QUOTED = re.compile(r'(?:"([^"]{12,400})")|(?:“([^”]{12,400})”)|(?:\'([^\']{20,400})\')')
_SPEAKER_AFTER = re.compile(
    r'(?:,|\s)\s*(?:said|says|told|added|noted|explained|wrote|stated|according to|'
    r'reported|claimed|argued|warned|admitted|confirmed|mentioned|tweeted|posted)\s+'
    r'([A-Z][\w\'\-]+(?:\s+[A-Z][\w\'\-]+){0,3})(?:\s*,?\s*(?:the\s+)?'
    r'([A-Za-z][\w\-]*(?:\s+[A-Za-z][\w\-]+){0,4}))?', re.IGNORECASE)
_SPEAKER_BEFORE = re.compile(
    r'\b([A-Z][\w\'\-]+(?:\s+[A-Z][\w\'\-]+){0,3})\s*(?:,\s*(?:the\s+)?'
    r'([A-Za-z][\w\-]*(?:\s+[A-Za-z][\w\-]+){0,4})?,)?\s*'
    r'(?:said|says|told|added|noted|explained|wrote|stated|claimed|argued|warned|'
    r'admitted|confirmed|tweeted|posted)\s*[:,]?\s*$', re.IGNORECASE)
_PARTIAL = re.compile(r"\b(?:said|told|according to)\b", re.IGNORECASE)
# "Huang told attendees": the subject of "told" is the speaker, not the audience.
_TOLD = re.compile(r"^\s*,?\s*((?:[A-Z][\w'\-]+\s+){0,3}[A-Z][\w'\-]+)\s+told\s+", re.IGNORECASE)


@dataclass
class Quote:
    text: str
    speaker: str = ""
    role: str = ""
    source_sentence: str = ""
    index: int = 0
    words: int = 0
    partial: bool = False

    def attribution(self) -> str:
        if self.speaker and self.role:
            return f"{self.speaker}, {self.role}"
        return self.speaker

    def render(self) -> str:
        """Blockquote-ready text with attribution."""
        body = squish(self.text).strip('"')
        who = self.attribution()
        return f"{body} - {who}" if who else body


def find(text: str) -> list[Quote]:
    """All quotes in a document with their speakers, in order of appearance."""
    sentences = split_sentences(text)
    out: list[Quote] = []
    for index, sentence in enumerate(sentences):
        for match in _QUOTED.finditer(sentence):
            body = squish(match.group(1) or match.group(2) or match.group(3) or "")
            if len(body.split()) < 3:
                continue
            speaker, role = _speaker(sentence, match)
            out.append(Quote(text=body, speaker=speaker, role=role, source_sentence=sentence,
                             index=index, words=len(body.split()),
                             partial=bool(_PARTIAL.search(sentence))))
    return out


def _speaker(sentence: str, match: re.Match) -> tuple[str, str]:
    """Attribute a quote from the words around it."""
    tail = sentence[match.end():]
    head = sentence[:match.start()]
    told = _TOLD.match(tail)
    if told:
        return told.group(1).strip(), ""
    found = _SPEAKER_AFTER.match(tail.strip().lstrip(",. ")) or _SPEAKER_AFTER.search(tail)
    if found:
        return found.group(1).strip(), (found.group(2) or "").strip()
    found = _SPEAKER_BEFORE.search(head)
    if found:
        return found.group(1).strip(), (found.group(2) or "").strip()
    return "", ""


def best(text: str, *, limit: int = 3, min_words: int = 6, max_words: int = 60) -> list[Quote]:
    """The most quotable lines: attributed, medium length, not marketing fluff."""
    candidates = [quote for quote in find(text)
                  if min_words <= quote.words <= max_words]
    if not candidates:
        candidates = [quote for quote in find(text) if quote.words >= 4]

    def score(quote: Quote) -> float:
        value = 0.0
        if quote.speaker:
            value += 2.0
        if quote.role:
            value += 1.0
        value += min(1.5, quote.words / 25)
        lowered = quote.text.lower()
        if any(word in lowered for word in ("we", "our", "i", "you")):
            value += 0.8
        if any(word in lowered for word in ("buy now", "available now", "subscribe", "discount",
                                            "offer", "deal", "% off", "free trial")):
            value -= 3.0
        if quote.text.count("!") > 1:
            value -= 1.0
        return value

    candidates.sort(key=lambda quote: (-score(quote), quote.index))
    seen: set[str] = set()
    out: list[Quote] = []
    for quote in candidates:
        key = quote.text[:40].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(quote)
        if len(out) >= limit:
            break
    return out


def strip_quotes(text: str) -> str:
    """Remove quoted spans — used before paraphrasing so quotes survive verbatim."""
    return _QUOTED.sub(" ", text)


def quote_density(text: str) -> float:
    """Quotes per 500 words — an authority signal for the quality gate."""
    word_total = max(1, len(text.split()))
    return round(len(find(text)) / word_total * 500, 3)
