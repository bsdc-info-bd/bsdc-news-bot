"""Keyword density, prominence, proximity and saturation.

Density alone is a trap: a page can hit 2% and still be irrelevant, or 0.4% and rank
because the term appears in the title, the first sentence and an H2. This module
measures all of those, plus n-gram coverage and stuffing risk, and reports a single
balanced score with the reason behind it.
"""

import math
import re
from collections import Counter

from ..cortex.text.normalize import squish
from ..cortex.text.tokenize import words

IDEAL_MIN = 0.4
IDEAL_MAX = 2.0
STUFFING = 3.2


def counts(text: str, keyword: str) -> dict[str, float | int]:
    """Occurrences, density and position data for one keyword."""
    body = squish(text or "")
    lowered = body.lower()
    tokens = words(body)
    total = max(1, len(tokens))
    phrase = keyword.lower().strip()
    if not phrase:
        return {"hits": 0, "density": 0.0, "first_position": 1.0, "spread": 0.0,
                "tokens": total}
    hits = len(re.findall(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered))
    if not hits:                                   # fall back to per-word matching
        parts = [part for part in phrase.split() if part]
        hits = min(Counter(tokens).get(part, 0) for part in parts) if parts else 0
    positions = [match.start() / max(1, len(lowered))
                 for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", lowered)]
    spread = (max(positions) - min(positions)) if len(positions) > 1 else 0.0
    return {
        "hits": hits,
        "density": round(hits / total * 100, 3),
        "first_position": round(positions[0], 3) if positions else 1.0,
        "spread": round(spread, 3),
        "tokens": total,
    }


def prominence(metric: dict) -> float:
    """0..1: how early and how often the keyword appears."""
    if not metric.get("hits"):
        return 0.0
    early = 1.0 - min(1.0, float(metric["first_position"]))
    frequency = min(1.0, math.log1p(int(metric["hits"])) / math.log(9))
    return round(0.6 * early + 0.4 * frequency, 3)


def proximity(text: str, keyword: str, *, window: int = 12) -> float:
    """0..1: how tightly the keyword's own words cluster (partial-match strength)."""
    parts = [part for part in keyword.lower().split() if part]
    if len(parts) < 2:
        return 1.0 if parts and parts[0] in squish(text).lower() else 0.0
    tokens = words(text)
    if not tokens:
        return 0.0
    hits = 0
    for index in range(len(tokens)):
        if tokens[index] != parts[0]:
            continue
        neighbourhood = tokens[index + 1: index + window]
        if all(part in neighbourhood for part in parts[1:]):
            hits += 1
    return round(min(1.0, hits / max(1, len(parts))), 3)


def saturation(text: str, keyword: str) -> float:
    """0..1 penalty for repeating the keyword too often in one paragraph."""
    worst = 0.0
    for paragraph in re.split(r"\n{2,}|</p>", text or ""):
        tokens = words(paragraph)
        if len(tokens) < 8:
            continue
        hits = sum(1 for token in tokens if token in keyword.lower().split())
        ratio = hits / len(tokens)
        worst = max(worst, ratio)
    return round(min(1.0, max(0.0, (worst - 0.12) * 4)), 3)


def ngram_coverage(text: str, keywords: list[str]) -> dict[str, float]:
    """Coverage of every planned keyword, so a plan can be verified."""
    body = squish(text or "").lower()
    return {keyword: round(body.count(keyword.lower()) / max(1, len(keyword.split())), 2)
            for keyword in keywords if keyword}


def score(*, density: float, prominence_value: float, in_title: bool, in_first_sentence: bool,
          in_headings: int = 0, in_meta: bool = False, in_url: bool = False) -> tuple[int, list[str]]:
    """0-100 keyword placement score with the reasons."""
    notes: list[str] = []
    total = 0.0
    if IDEAL_MIN <= density <= IDEAL_MAX:
        total += 22
        notes.append(f"density {density:.2f}% is in the {IDEAL_MIN}-{IDEAL_MAX}% band")
    elif density > STUFFING:
        total -= 12
        notes.append(f"density {density:.2f}% risks a stuffing penalty")
    elif density > IDEAL_MAX:
        total += 12
        notes.append(f"density {density:.2f}% is above the ideal band")
    else:
        total += 10 if density > 0 else 0
        notes.append(f"density {density:.2f}% is thin")
    total += 20 * prominence_value
    notes.append(f"prominence {prominence_value:.2f}")
    if in_title:
        total += 20
        notes.append("keyword in the title tag")
    else:
        notes.append("keyword missing from the title tag")
    if in_first_sentence:
        total += 14
        notes.append("keyword in the opening sentence")
    if in_headings:
        total += min(12, 4 * in_headings)
        notes.append(f"keyword in {in_headings} heading(s)")
    if in_meta:
        total += 8
        notes.append("keyword in the meta description")
    if in_url:
        total += 6
        notes.append("keyword in the URL slug")
    return int(round(max(0, min(100, total)))), notes


def stuffing_risk(text: str, keywords: list[str]) -> list[str]:
    """Phrases repeated far more than a human would repeat them."""
    tokens = words(text)
    total = max(1, len(tokens))
    flagged: list[str] = []
    for keyword in keywords:
        parts = keyword.lower().split()
        if not parts:
            continue
        hits = sum(1 for token in tokens if token in parts)
        if hits / total > 0.06 and hits > 6:
            flagged.append(f"{keyword!r} at {hits / total:.1%} of all words")
    return flagged


def report(text: str, *, primary: str, secondary: list[str] | None = None,
           title: str = "", meta: str = "", slug: str = "",
           headings: list[str] | None = None) -> dict:
    """Everything the planner needs about one article's keyword placement."""
    secondary = secondary or []
    headings = headings or []
    metric = counts(text, primary)
    first_sentence = squish(text).split(". ")[0] if squish(text) else ""
    heading_text = " ".join(headings).lower()
    value, notes = score(
        density=float(metric["density"]), prominence_value=prominence(metric),
        in_title=primary.lower() in title.lower(),
        in_first_sentence=primary.lower() in first_sentence.lower(),
        in_headings=heading_text.count(primary.lower()),
        in_meta=primary.lower() in meta.lower(),
        in_url=any(part in slug.lower() for part in primary.lower().split()),
    )
    return {
        "primary": primary, "metric": metric, "score": value, "notes": notes,
        "proximity": proximity(text, primary), "saturation": saturation(text, primary),
        "coverage": ngram_coverage(text, [primary, *secondary]),
        "stuffing": stuffing_risk(text, [primary, *secondary]),
        "secondary": {term: counts(text, term)["hits"] for term in secondary[:8]},
    }
