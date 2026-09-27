"""Meta description, robots meta and the social cards.

The description is written from the article's own lede and key points, trimmed at
clause boundaries so it never ends mid-fact, and checked for length, keyword
presence and a call to read on. Robots and social tags are derived, never guessed.
"""

import re

from ..cortex.text import pos
from ..cortex.text.normalize import squish

MIN_LENGTH = 120
IDEAL_LENGTH = 155
MAX_LENGTH = 160
_DANGLING = frozenset(["in", "of", "to", "at", "for", "on", "by", "with", "from", "and",
                       "or", "the", "a", "an", "its", "their", "as", "that", "which"])


def description(*, lede: str = "", dek: str = "", key_points: list[str] | None = None,
                keyword: str = "", minimum: int = MIN_LENGTH, maximum: int = MAX_LENGTH) -> str:
    """Best available description, trimmed without losing a figure."""
    points = [squish(item) for item in (key_points or []) if item]
    sources = [squish(lede), squish(dek), *points]
    joined = [item for item in sources if item]
    if len(joined) > 1:
        joined.append(f"{joined[0].rstrip('.')}. {joined[1]}")
    for candidate in joined:
        fitted = _fit(candidate.rstrip("."), minimum=minimum, maximum=maximum)
        if fitted:
            return _finish(fitted, keyword, maximum)
    fallback = next((item for item in joined if item), "")
    return _finish(fallback[:maximum].rstrip(" ,;:-"), keyword, maximum)


def _fit(text: str, *, minimum: int, maximum: int) -> str:
    if minimum <= len(text) <= maximum:
        return text
    if len(text) < minimum:
        return ""
    boundaries = [match.end() for match in re.finditer(r"[,;] |\.\s", text)]
    for position in reversed([item for item in boundaries if item <= maximum - 1]):
        piece = text[:position].rstrip(" ,;:-")
        if _digits(piece) == _digits(text[:maximum]) and len(piece) >= minimum - 25:
            return piece
    words = text.split()
    while words and len(" ".join(words)) > maximum:
        words.pop()
    words = _strip_dangling(words)
    piece = " ".join(words).rstrip(" ,;:-")
    if _digits(piece) != _digits(text[: len(piece) + 12]) or len(piece) < minimum - 25:
        return ""
    return piece


def _strip_dangling(words: list[str]) -> list[str]:
    """Drop trailing function words and adjectives so the sentence still means something.

    Ending on "through a single interoperable" loses the noun it modifies, which is
    worse than a shorter description that stops cleanly at "transfers".
    """
    while words:
        last = words[-1].lower().strip(".,;:")
        if last in _DANGLING:
            words.pop()
            continue
        if pos.tag_token(last).startswith(("JJ", "DT", "IN", "CC", "WDT", "WP")):
            words.pop()
            continue
        break
    return words


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _finish(text: str, keyword: str, maximum: int) -> str:
    text = squish(text).strip()
    if not text:
        return ""
    if keyword and len(keyword.split()) > 1 and keyword.lower() not in text.lower():
        room = maximum - len(keyword) - 3          # ": " plus the closing full stop
        text = f"{keyword.title()}: {text[:max(0, room)].rstrip(' ,;:-')}"
    return text if text.endswith((".", "!", "?")) else f"{text}."


def robots(*, index: bool = True, follow: bool = True, noarchive: bool = False,
           nosnippet: bool = False, max_snippet: int = -1, max_image: str = "large",
           after: str = "") -> str:
    """The robots meta directive string."""
    parts = ["index" if index else "noindex", "follow" if follow else "nofollow"]
    if noarchive:
        parts.append("noarchive")
    if nosnippet:
        parts.append("nosnippet")
    if max_snippet >= 0:
        parts.append(f"max-snippet:{max_snippet}")
    if max_image:
        parts.append(f"max-image-preview:{max_image}")
    if after:
        parts.append(f"unavailable_after: {after}")
    return ", ".join(parts)


def open_graph(*, title: str, description: str, url: str, image: str = "",
               site_name: str = "", locale: str = "en_US", article_type: str = "article",
               published: str = "", modified: str = "", author: str = "",
               tags: list[str] | None = None, image_alt: str = "") -> dict:
    """Open Graph tags for Facebook, LinkedIn, Messenger and WhatsApp previews."""
    data = {
        "og:type": article_type,
        "og:title": title[:95],
        "og:description": description[:200],
        "og:url": url,
        "og:site_name": site_name,
        "og:locale": locale,
    }
    if image:
        data["og:image"] = image
        data["og:image:alt"] = (image_alt or title)[:125]
        data["og:image:width"] = "1200"
        data["og:image:height"] = "630"
    if published:
        data["article:published_time"] = published
    if modified:
        data["article:modified_time"] = modified
    if author:
        data["article:author"] = author
    for tag in (tags or [])[:6]:
        data.setdefault("article:tag", tag)
    return {key: value for key, value in data.items() if value}


def twitter_card(*, title: str, description: str, image: str = "", handle: str = "",
                 card: str = "summary_large_image", image_alt: str = "") -> dict:
    """Twitter/X card tags."""
    data = {"twitter:card": card, "twitter:title": title[:70],
            "twitter:description": description[:200]}
    if image:
        data["twitter:image"] = image
        data["twitter:image:alt"] = (image_alt or title)[:125]
    if handle:
        data["twitter:site"] = handle if handle.startswith("@") else f"@{handle}"
        data["twitter:creator"] = data["twitter:site"]
    return data


def canonical(url: str, *, strip_query: bool = True) -> str:
    """The canonical URL: absolute, no tracking query, no fragment."""
    url = squish(url or "")
    if not url:
        return ""
    url = url.split("#", 1)[0]
    if strip_query:
        url = url.split("?", 1)[0]
    return url.rstrip("/") + "/" if url.count("/") <= 2 else url


def _plain(value) -> str:
    """Social cards render text verbatim, so markup must never reach them."""
    if not isinstance(value, str):
        return value
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def tags_html(og: dict, twitter: dict, *, extra: dict | None = None) -> str:
    og = {key: _plain(value) for key, value in (og or {}).items()}
    twitter = {key: _plain(value) for key, value in (twitter or {}).items()}
    extra = {key: _plain(value) for key, value in (extra or {}).items()}
    """Rendered social meta tags (used when the platform allows raw head HTML)."""
    lines = [f'<meta property="{key}" content="{_escape(value)}" />' for key, value in og.items()]
    lines += [f'<meta name="{key}" content="{_escape(value)}" />' for key, value in twitter.items()]
    for key, value in (extra or {}).items():
        lines.append(f'<meta name="{key}" content="{_escape(value)}" />')
    return "\n".join(lines)


def _escape(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
