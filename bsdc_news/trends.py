"""Free trending-topic signal from the public Google Trends RSS feed."""

from __future__ import annotations

import feedparser

from .dedupe import keywords
from .http import HttpClient
from .log import get_logger
from .utils import normalize_space

log = get_logger("trends")

TRENDS_URL = "https://trends.google.com/trending/rss?geo={geo}"


def fetch_trending_terms(http: HttpClient, geos: list[str], limit_per_geo: int = 25) -> list[str]:
    terms: list[str] = []
    for geo in geos or []:
        try:
            resp = http.get(TRENDS_URL.format(geo=geo), timeout=12)
            if resp.status_code != 200:
                log.debug("Trends %s returned HTTP %s", geo, resp.status_code)
                continue
            parsed = feedparser.parse(resp.content)
            for entry in parsed.entries[:limit_per_geo]:
                term = normalize_space(entry.get("title", ""))
                if term:
                    terms.append(term.lower())
                # headlines attached to the trend are an even better signal
                for key in ("ht_news_item_title",):
                    if entry.get(key):
                        terms.append(normalize_space(entry[key]).lower())
        except Exception as exc:  # trends are optional
            log.debug("Trends fetch failed for %s: %s", geo, exc)
    uniq = list(dict.fromkeys(t for t in terms if t))
    if uniq:
        log.info("   📈 %d trending terms loaded (%s)", len(uniq), ", ".join(geos))
    return uniq


def trend_match(title: str, terms: list[str]) -> str:
    """Return the trending term matched by *title*, or ''."""
    if not terms:
        return ""
    title_kw = keywords(title)
    title_l = title.lower()
    for term in terms:
        term_kw = keywords(term)
        if not term_kw:
            continue
        if len(term_kw) == 1:
            word = next(iter(term_kw))
            if len(word) >= 4 and word in title_kw:
                return term
        elif term in title_l or len(term_kw & title_kw) >= max(2, int(len(term_kw) * 0.6)):
            return term
    return ""
