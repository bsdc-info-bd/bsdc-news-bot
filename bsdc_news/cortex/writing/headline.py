"""Headline generation and scoring.

Candidates come from the source title, from headline templates filled with
extracted facts, and from keyword-first rewrites. Each candidate is scored on
seven criteria — length, keyword position, informativeness (numbers/entities),
power words, clickbait penalty, novelty against published titles and style —
then the best is chosen. Nothing is invented: every slot is filled from the text.
"""

import re
from dataclasses import dataclass

from ..analysis.clickbait import is_clickbait, sanitize_headline, score_headline
from ..lexicon import loader
from ..semantic.similarity import title_similarity
from ..text.normalize import squish
from .style import smart_case, title_case

IDEAL_MIN = 42
IDEAL_MAX = 62
HARD_MAX = 70
_VERB = re.compile(r"\b(unveils?|launches?|releases?|announces?|confirms?|cuts?|raises?|"
                   r"adds?|brings?|ships?|rolls out|opens?|expands?|tests?|plans?|"
                   r"promises?|delivers?|reveals?|updates?|ends?|starts?|drops?)\b", re.IGNORECASE)
_FILLER_TAIL = re.compile(r"\s*[-|:–]\s*(?:here's what|what you need to know|everything we know|"
                          r"and it's|and it is|full details|more inside|read more).*$", re.IGNORECASE)
_PREFIX_NOISE = re.compile(r"^(?:exclusive|breaking|update|report|opinion|analysis|review)\s*[:|\-]\s*", re.IGNORECASE)


@dataclass
class HeadlineCandidate:
    text: str
    score: float
    origin: str
    notes: list[str]

    def as_dict(self) -> dict:
        return {"text": self.text, "score": round(self.score, 3), "origin": self.origin,
                "notes": self.notes}


_SUFFIX = re.compile(r"\s*(?:[-|–—:]|\|)\s*([^\-|–—:]{2,34})$")


def strip_site_suffix(text: str) -> str:
    """Drop trailing site/section names (" - TechCrunch", "| bsdc news").

    Only when the tail carries no facts: no digits, no money, no percentages and
    at most four words, so " - ships in 2026" is never removed.
    """
    match = _SUFFIX.search(text)
    if not match:
        return text
    tail = match.group(1).strip()
    tokens = tail.split()
    if len(tokens) > 4:
        return text
    if any(ch.isdigit() for ch in tail) or any(ch in tail for ch in "$%€£৳"):
        return text
    return text[:match.start()].strip()


def shorten(text: str, *, limit: int = IDEAL_MAX, primary_keyword: str = "") -> list[str]:
    """Trim a long source headline down to the SERP sweet spot without inventing anything.

    Cuts are made only at punctuation or conjunction boundaries, and a candidate
    that keeps the primary keyword plus a number is preferred.
    """
    text = clean(text)
    if len(text) <= limit:
        return [text] if text else []
    out: list[str] = []
    for pattern in (r"[,:;]\s+", r"\s+(?:and|but|as|after|while|with)\s+", r"\s+-\s+"):
        position = len(text)
        for match in re.finditer(pattern, text):
            piece = text[:match.start()].strip()
            if IDEAL_MIN - 12 <= len(piece) <= limit and piece not in out:
                out.append(piece)
            if match.start() < position:
                position = match.start()
    tokens = text.split()
    while tokens and len(" ".join(tokens)) > limit:
        tokens.pop()
    if tokens:
        piece = " ".join(tokens).strip(" ,;:-")
        if piece not in out:
            out.append(piece)
    if primary_keyword:
        key = primary_keyword.lower()
        out.sort(key=lambda candidate: (key not in candidate.lower(),
                                        -sum(ch.isdigit() for ch in candidate), len(candidate)))
    return out[:3]


def clean(headline: str) -> str:
    """Strip feed noise: site suffixes, filler tails, all-caps, emoji."""
    text = squish(headline)
    text = _PREFIX_NOISE.sub("", text)
    text = _FILLER_TAIL.sub("", text)
    text = strip_site_suffix(text)
    text = re.sub(r"[^\w\s\-–—:,'\"&\.\?%$/€£₹৳]", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" -–—:|")
    return sanitize_headline(text)


def score(headline: str, *, primary_keyword: str = "", entities: list[str] | None = None,
          numbers: list[str] | None = None, published: list[str] | None = None,
          power_words: set[str] | None = None) -> tuple[float, list[str]]:
    """0..1 headline quality with the reasons behind the score."""
    entities = entities or []
    numbers = numbers or []
    published = published or []
    power_words = power_words if power_words is not None else loader.power_words()
    notes: list[str] = []
    text = clean(headline)
    if not text:
        return 0.0, ["empty"]
    lowered = text.lower()
    tokens = text.split()
    total = 0.0

    length = len(text)
    if IDEAL_MIN <= length <= IDEAL_MAX:
        total += 0.24
        notes.append(f"length {length} is in the SERP sweet spot")
    elif length < 30:
        total += 0.06
        notes.append(f"too short ({length} chars)")
    elif length > HARD_MAX:
        total += 0.08
        notes.append(f"will be truncated ({length} chars)")
    else:
        total += 0.16
        notes.append(f"length {length} acceptable")

    if primary_keyword:
        parts = primary_keyword.lower().split()
        if primary_keyword.lower() in lowered:
            position = lowered.find(primary_keyword.lower()) / max(1, length)
            total += 0.22 if position < 0.35 else 0.14
            notes.append(f"primary keyword present at {position:.0%} of the title")
        elif any(part in lowered.split() for part in parts):
            total += 0.09
            notes.append("partial keyword match")
        else:
            notes.append("primary keyword missing")

    informative = min(2, len(numbers)) * 0.06 + min(2, len(entities)) * 0.05
    if informative:
        total += informative
        notes.append(f"{len(numbers)} number(s), {len(entities)} named entit(y/ies)")
    if _VERB.search(text):
        total += 0.08
        notes.append("active verb")
    else:
        notes.append("no active verb")

    power_hits = [token.strip(".,;:!?") for token in tokens if token.lower().strip(".,;:") in power_words]
    if power_hits:
        total += min(0.10, 0.035 * len(power_hits))
        notes.append(f"power words: {', '.join(power_hits[:3])}")

    bait, reasons = score_headline(text)
    if bait:
        total -= 0.45 * bait
        notes.extend(reasons[:2])
    if text.endswith("?"):
        total -= 0.05
        notes.append("question headline")
    if published:
        closest = max(title_similarity(text, other) for other in published[:200])
        if closest > 0.90:
            total -= 0.25
            notes.append(f"near-identical to a published headline ({closest:.2f})")
        elif closest > 0.75:
            total -= 0.12
            notes.append(f"close to a published headline ({closest:.2f})")
        elif closest > 0.55:
            total -= 0.04
            notes.append(f"echoes a published headline ({closest:.2f})")
    if any(token.isupper() and len(token) > 3 for token in tokens):
        total -= 0.06
        notes.append("shouting capitals")
    return round(max(0.0, min(1.0, total)), 4), notes


def candidates(source_title: str, *, primary_keyword: str = "", secondary: list[str] | None = None,
               entities: list[str] | None = None, actor: str = "", verb: str = "",
               detail: str = "", numbers: list[str] | None = None, place: str = "",
               audience: str = "", alternative: str = "", claim: str = "",
               time: str = "", subject: str = "",
               allow_contextual: bool = False) -> list[HeadlineCandidate]:
    """Build headline candidates from templates filled only with real facts."""
    secondary = secondary or []
    entities = entities or []
    numbers = numbers or []
    subject = subject or primary_keyword or (entities[0] if entities else "")
    detail_value = detail or (numbers[0] if numbers else "") or (secondary[0] if secondary else "")
    # Slots are filled ONLY from evidence. A template that needs something the
    # source does not state is skipped rather than padded with a guess, because an
    # invented "ships this year" in a headline is a factual error.
    slots = {
        "actor": actor or (entities[0] if entities else ""),
        "verb": verb,
        "object": subject,
        "detail": detail_value,
        "place": place,
        "audience": audience,
        "alternative": alternative or (secondary[1] if len(secondary) > 1 else ""),
        "claim": claim or detail_value,
        "number": str(len(numbers)) if numbers else "",
        "percent": next((item for item in numbers if "%" in item), ""),
        "price": next((item for item in numbers if item.startswith(("$", "€", "£", "৳"))), ""),
        "time": time,
    }
    out: list[HeadlineCandidate] = []
    cleaned = clean(source_title)
    if cleaned:
        out.append(HeadlineCandidate(text=cleaned, score=0.0, origin="source", notes=[]))
        for trimmed in shorten(cleaned, primary_keyword=primary_keyword):
            if trimmed and trimmed != cleaned:
                out.append(HeadlineCandidate(text=trimmed, score=0.0, origin="source-shortened",
                                             notes=[]))
        if primary_keyword and primary_keyword.lower() not in cleaned.lower():
            out.append(HeadlineCandidate(text=f"{cleaned}: {primary_keyword.title()} explained",
                                         score=0.0, origin="keyword-appended", notes=[]))
    for template in loader.headline_templates():
        if template.get("contextual") and not allow_contextual:
            # Asserting availability, price, place or timing needs verified evidence
            # from one place in the source; without it the headline could be wrong.
            continue
        pattern = template["pattern"]
        needed = set(re.findall(r"\{(\w+)\}", pattern))
        if any(not str(slots.get(slot, "")).strip() for slot in needed):
            continue
        try:
            text = pattern.format(**{slot: slots.get(slot, "") for slot in needed})
        except (KeyError, IndexError):
            continue
        text = clean(text)
        if not text or len(text.split()) < 4:
            continue
        out.append(HeadlineCandidate(text=text, score=0.0, origin=f"template:{pattern[:28]}",
                                     notes=[]))
    if subject and detail_value:
        out.append(HeadlineCandidate(text=clean(f"{title_case(subject)} {detail_value}"),
                                     score=0.0, origin="keyword-first", notes=[]))
    if subject and numbers:
        out.append(HeadlineCandidate(text=clean(f"{title_case(subject)}: {numbers[0]} and what it means"),
                                     score=0.0, origin="number-led", notes=[]))
    return out


def best(source_title: str, *, primary_keyword: str = "", secondary: list[str] | None = None,
         entities: list[str] | None = None, numbers: list[str] | None = None,
         published: list[str] | None = None, actor: str = "", verb: str = "",
         detail: str = "", place: str = "", alternative: str = "", claim: str = "",
         time: str = "", subject: str = "",
         allow_contextual: bool = False) -> tuple[str, list[HeadlineCandidate]]:
    """Score every candidate and return the winner plus the ranked list."""
    pool = candidates(source_title, primary_keyword=primary_keyword, secondary=secondary,
                      entities=entities, actor=actor, verb=verb, detail=detail,
                      numbers=numbers, place=place, alternative=alternative,
                      claim=claim, time=time, subject=subject,
                      allow_contextual=allow_contextual)
    for candidate in pool:
        value, notes = score(candidate.text, primary_keyword=primary_keyword,
                             entities=entities or [], numbers=numbers or [],
                             published=published or [])
        if candidate.origin.startswith("source"):
            # Grounded in the reporter's own words: a template can only reframe.
            value += 0.10
            notes.append("grounded in the source headline")
        if candidate.text.endswith("?"):
            value -= 0.04
            notes.append("question form is a weaker SERP title")
        candidate.score = round(value, 4)
        candidate.notes = notes
    pool.sort(key=lambda item: (-item.score, len(item.text)))
    if not pool:
        return clean(source_title), []
    winner = pool[0]
    text = smart_case(winner.text)
    if is_clickbait(text):
        fallback = next((candidate for candidate in pool if not is_clickbait(candidate.text)), None)
        if fallback:
            text = smart_case(fallback.text)
    return text[:HARD_MAX].rstrip(" ,;:-–—"), pool


def variants(headline: str, *, count: int = 3) -> list[str]:
    """Alternative headlines for social posts (never clickbait)."""
    out = [headline]
    if ":" in headline:
        left, right = headline.split(":", 1)
        out.append(f"{right.strip()} - {left.strip()}")
        out.append(right.strip().capitalize())
    else:
        out.append(headline)
    tokens = headline.split()
    if len(tokens) > 6:
        out.append(" ".join(tokens[:6]))
    return list(dict.fromkeys(item for item in out if item))[:count]
