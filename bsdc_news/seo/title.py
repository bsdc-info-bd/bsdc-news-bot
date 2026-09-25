"""Title tag construction: the single highest-leverage on-page signal.

Rules encoded here are the ones that actually move rankings and clicks: the primary
keyword as early as possible, 50-60 characters before the brand suffix, no
duplication of the H1, no keyword stuffing, sentence case, and a brand suffix that
is dropped when the title would otherwise be truncated mid-word.
"""

import re

from ..cortex.text.normalize import squish

BRAND_SEPARATOR = "|"
MIN_LENGTH = 30
IDEAL_MAX = 60
HARD_MAX = 65
_FILLER = re.compile(r"\s*[-|–—:]\s*(read more|full story|details|update\d*|news|latest)\s*$",
                     re.IGNORECASE)
_DUPLICATE_WORD = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)


_DANGLING_TAIL = re.compile(
    r"(?:\s+(?:as|and|or|but|to|of|in|on|at|by|for|with|from|after|over|amid|about|"
    r"against|during|under|between|the|a|an|says|said|while|that|which|it|its))+$", re.IGNORECASE)


def clean(title: str) -> str:
    """Strip feed noise, filler tails and repeated words."""
    text = squish(re.sub(r"<[^>]+>", " ", title or ""))
    text = _FILLER.sub("", text)
    text = re.sub(r"[^\w\s\-–—:,'\"&\.\?%$/€£৳]", " ", text)
    text = _DUPLICATE_WORD.sub(r"\1", text)
    return squish(text).strip(" -–—:|")


def keyword_first(title: str, keyword: str) -> str:
    """Move the primary keyword towards the front when it sits in the back half."""
    title, keyword = clean(title), squish(keyword)
    if not keyword or keyword.lower() in title.lower()[: len(keyword) + 8]:
        return title
    index = title.lower().find(keyword.lower())
    if index < 0:
        return title
    if index <= len(title) * 0.4:
        return title
    head, tail = title[:index].strip(" ,;:-"), title[index:].strip()
    if not head:
        return title
    return squish(f"{tail.rstrip('.')} - {head}")[:HARD_MAX].strip(" -")


def with_brand(title: str, site_name: str = "", *, separator: str = BRAND_SEPARATOR,
               limit: int = HARD_MAX) -> str:
    """Append the brand, but only while the whole thing still fits the SERP."""
    title = clean(title)
    if not site_name:
        return title[:limit]
    suffix = f" {separator} {site_name}"
    if len(title) + len(suffix) <= limit:
        return f"{title}{suffix}"
    room = limit - len(suffix)
    if room < MIN_LENGTH:
        return _trim_dangling(title[:limit])     # the title matters more than the brand
    cut = title[:room]
    for boundary in (" ", ",", "-"):
        if boundary in cut[room - 14:]:
            cut = cut[: cut.rfind(boundary, room - 14)]
            break
    return f"{_trim_dangling(cut)}{suffix}"


def _trim_dangling(text: str) -> str:
    """Cut a title back to the last word that carries meaning.

    Truncating on a character budget used to publish "…to 9.5 percent as | bsdc news",
    which reads like a mistake in the search results.
    """
    return _DANGLING_TAIL.sub("", (text or "").rstrip(" ,;:-")).rstrip(" ,;:-")


def differs_from_h1(title_tag: str, h1: str, *, threshold: float = 0.9) -> bool:
    """True when the title tag is not a byte-for-byte copy of the H1."""
    a, b = clean(title_tag).lower(), clean(h1).lower()
    if not a or not b:
        return True
    if a == b:
        return False
    overlap = len(set(a.split()) & set(b.split())) / max(1, len(set(a.split()) | set(b.split())))
    return overlap < threshold


def length_score(title: str) -> float:
    """0..1: how well the title uses the pixel budget."""
    length = len(clean(title))
    if MIN_LENGTH <= length <= IDEAL_MAX:
        return 1.0
    if length < MIN_LENGTH:
        return max(0.2, length / MIN_LENGTH)
    if length <= HARD_MAX:
        return 0.85
    return max(0.2, 1.0 - (length - HARD_MAX) / 60)


def stuffing_score(title: str, keywords: list[str] | None = None) -> float:
    """0..1 penalty: repeated keywords or an unnaturally dense title."""
    tokens = re.findall(r"[a-z0-9]+", clean(title).lower())
    if not tokens:
        return 0.0
    keywords = [keyword.lower() for keyword in (keywords or []) if keyword]
    repeats = len(tokens) - len(set(tokens))
    penalty = 0.12 * repeats
    for keyword in keywords:
        parts = keyword.split()
        hits = sum(1 for token in tokens if token in parts)
        if len(parts) and hits / len(tokens) > 0.5:
            penalty += 0.25
    return round(min(1.0, penalty), 3)


def build(headline: str, *, keyword: str = "", site_name: str = "",
          category: str = "", prefer_keyword_first: bool = True) -> str:
    """The finished <title> for one article."""
    title = clean(headline)
    if keyword and prefer_keyword_first:
        title = keyword_first(title, keyword)
    if category and len(title) < MIN_LENGTH:
        title = squish(f"{title} - {category}")[:HARD_MAX]
    return with_brand(title, site_name)


def candidates(headline: str, *, keyword: str = "", site_name: str = "",
               category: str = "") -> list[tuple[str, str]]:
    """(title, rationale) pairs so the choice can be audited."""
    out = [
        (build(headline, keyword=keyword, site_name=site_name, category=category),
         "keyword-first with brand suffix"),
        (with_brand(clean(headline), site_name), "source headline with brand suffix"),
        (clean(headline)[:HARD_MAX], "headline alone, maximum title space"),
    ]
    if keyword:
        out.append((with_brand(f"{keyword.title()}: {clean(headline)}", site_name),
                    "keyword prefixed as a label"))
    seen: set[str] = set()
    unique = []
    for title, reason in out:
        if title and title.lower() not in seen:
            seen.add(title.lower())
            unique.append((title, reason))
    return unique
