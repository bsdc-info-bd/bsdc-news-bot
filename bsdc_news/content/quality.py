"""Quality gates for generated articles.

Scores structure, length, originality (n-gram overlap with the source),
factual safety (numbers in the output must appear in the source) and
leftovers such as prompt echoes or markdown.  A score below
``publishing.min_quality_score`` rejects the draft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from ..dedupe import tokens
from ..utils import strip_tags, word_count

PROMPT_LEAKS = re.compile(
    r"(as an ai|language model|i cannot|i can't help|here is the (rewritten|article)|"
    r"source material|original headline|json object|return only|<<<|>>>|\bRULES\b)", re.I)
MARKDOWN_LEFTOVER = re.compile(r"(^|\n)\s*(#{1,6}\s|\*\*|__|```)")


@dataclass
class QualityReport:
    score: int
    words: int
    passed: bool
    issues: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def _ngrams(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def overlap_ratio(generated: str, source: str, n: int = 8) -> float:
    """Share of the generated text's 8-grams copied verbatim from the source."""
    gen = tokens(generated)
    src = tokens(source)
    if len(gen) < n or len(src) < n:
        return 0.0
    g = _ngrams(gen, n)
    return len(g & _ngrams(src, n)) / max(1, len(g))


_NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s?(%|percent|million|billion|trillion|bn|m|k))?",
                     re.I)


def _numbers(text: str) -> set[str]:
    out = set()
    for num, _unit in _NUM_RE.findall(text or ""):
        clean = num.replace(",", "")
        if len(clean.replace(".", "")) >= 2 or "." in clean:  # ignore single digits (list counts etc.)
            out.add(clean.rstrip("0").rstrip(".") if "." in clean else clean)
    return out


def unsupported_numbers(generated: str, source: str) -> set[str]:
    gen = _numbers(generated)
    src = _numbers(source)
    years_ok = {str(y) for y in range(1990, 2036)}
    return {n for n in gen - src if n not in years_ok}


def assess(body_html: str, source_text: str, *, min_words: int = 450, target_words: int = 750,
           min_score: int = 55, ai_generated: bool = True) -> QualityReport:
    soup = BeautifulSoup(body_html or "", "lxml")
    text = strip_tags(body_html)
    words = word_count(text)
    issues: list[str] = []
    score = 100
    h2 = len(soup.find_all("h2"))
    paras = [p for p in soup.find_all("p") if word_count(p.get_text()) >= 5]
    lists = len(soup.find_all(["ul", "ol"]))

    if ai_generated:
        if words < min_words:
            deficit = (min_words - words) / max(1, min_words)
            score -= int(15 + 45 * deficit)
            issues.append(f"too short ({words} < {min_words} words)")
        elif words < target_words * 0.8:
            score -= 5
        if h2 < 2:
            score -= 12
            issues.append(f"only {h2} <h2> subheadings")
        if len(paras) < 5:
            score -= 10
            issues.append(f"only {len(paras)} paragraphs")
        overlap = overlap_ratio(text, source_text)
        if overlap > 0.35:
            score -= 35
            issues.append(f"copies the source too closely ({overlap:.0%} 8-gram overlap)")
        elif overlap > 0.2:
            score -= 12
            issues.append(f"high verbatim overlap ({overlap:.0%})")
        bad_numbers = unsupported_numbers(text, source_text)
        if len(bad_numbers) >= 3:
            score -= 25
            issues.append(f"numbers not found in source: {', '.join(sorted(bad_numbers)[:6])}")
        elif bad_numbers:
            score -= 6 * len(bad_numbers)
            issues.append(f"check numbers: {', '.join(sorted(bad_numbers))}")
    else:
        overlap = 0.0
        bad_numbers = set()
        if words < 120:
            score -= 40
            issues.append(f"brief too short ({words} words)")

    if PROMPT_LEAKS.search(text):
        score -= 40
        issues.append("prompt/assistant text leaked into the article")
    if MARKDOWN_LEFTOVER.search(body_html or ""):
        score -= 8
        issues.append("markdown leftovers")
    long_paras = [p for p in paras if word_count(p.get_text()) > 140]
    if long_paras:
        score -= 4
        issues.append(f"{len(long_paras)} very long paragraph(s)")
    if not lists and ai_generated:
        score -= 3

    score = max(0, min(100, score))
    return QualityReport(
        score=score, words=words, passed=score >= min_score, issues=issues,
        metrics={"h2": h2, "paragraphs": len(paras), "lists": lists,
                 "overlap": round(overlap, 3), "unsupported_numbers": sorted(bad_numbers)[:10]},
    )


def reading_time(words: int, wpm: int = 225) -> int:
    return max(1, round(words / wpm))
