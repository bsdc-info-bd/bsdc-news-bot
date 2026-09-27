"""Editorial filters that reject items before any expensive work happens."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .feeds import FeedItem
from .utils import host_of, hours_since, word_count


@dataclass
class FilterDecision:
    ok: bool
    reason: str = ""


# Titles that are almost never real news
_LOW_VALUE_PATTERNS = [
    r"\b(\d{1,2}|\d{1,3}%) (best|top) \b",
    r"^\s*(the )?best .+ (for|in) 20\d\d",
    r"\bpromo codes?\b",
    r"\bcoupons?\b",
    r"\b(save|get) \$?\d+%? off\b",
    r"\bdeals? of the (day|week)\b",
    r"^\s*today'?s (wordle|connections|strands|quordle)",
    r"\bnyt (connections|mini|wordle)\b",
    r"\bhints? and answers?\b",
    r"^\s*(watch|listen)\s*:",
    r"\bpodcast\b.*\bepisode\b",
    r"\bsponsored\b",
    r"\bwebinar\b",
    r"\bdeals? and freebies\b",
    r"\bapp deals\b",
    r"^\s*the sideload\b",
    r"\bpodcast\b",
    r"\b(this|with this) \$\d[\d,.]*\b",          # "…with this $99 card" shopping posts
    r"\b(drops?|down) to \$\d[\d,.]*",              # "drops to $1,799"
    r"\bup to \$\d[\d,.]* off\b",
    r"\bearly access (sale|deals?)\b",
    r"\b(amazon|walmart|best buy) deal\b",
]
_LOW_VALUE_RE = re.compile("|".join(_LOW_VALUE_PATTERNS), re.I)
_NON_LATIN_RE = re.compile(r"[^\x00-\x7F\u00C0-\u024F\u2018-\u201F\u2013\u2014\u2026\u20AC\u00A3]")


def looks_english(text: str) -> bool:
    if not text:
        return False
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    foreign = sum(1 for c in letters if _NON_LATIN_RE.match(c))
    return foreign / len(letters) < 0.2


class ItemFilter:
    def __init__(self, settings) -> None:
        f = settings.get("filters", {})
        self.blocked_keywords = [k.lower() for k in f.get("blocked_keywords", [])]
        self.blocked_patterns = [p.lower() for p in f.get("blocked_url_patterns", [])]
        self.blocked_domains = {d.lower().removeprefix("www.") for d in f.get("blocked_domains", [])}
        self.required_language = (f.get("required_language") or "").lower()
        self.min_title_words = int(f.get("min_title_words", 4))
        self.max_age = float(settings.get("publishing.max_article_age_hours", 36))

    def check(self, item: FeedItem) -> FilterDecision:
        title_l = item.title.lower()
        url_l = item.url.lower()
        if word_count(item.title) < self.min_title_words:
            return FilterDecision(False, "title too short")
        for kw in self.blocked_keywords:
            if kw and kw in title_l:
                return FilterDecision(False, f"blocked keyword '{kw}'")
        if _LOW_VALUE_RE.search(item.title):
            return FilterDecision(False, "low-value headline (deals/listicle/puzzle)")
        for pattern in self.blocked_patterns:
            if pattern and pattern in url_l:
                return FilterDecision(False, f"blocked url pattern '{pattern}'")
        if host_of(item.url) in self.blocked_domains:
            return FilterDecision(False, "blocked domain")
        if item.published is not None and hours_since(item.published) > self.max_age:
            return FilterDecision(False, f"older than {self.max_age:.0f}h")
        if self.required_language == "en" and item.language.startswith("en") and not looks_english(item.title):
            return FilterDecision(False, "title not in English")
        return FilterDecision(True)
