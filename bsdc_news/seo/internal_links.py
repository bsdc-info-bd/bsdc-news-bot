"""Internal linking: choose which existing posts to link, and with what anchor.

Internal links are the one ranking lever a Blogger site fully controls. This module
ranks candidate posts by semantic relevance to the article (not just shared words),
rotates anchor text so the same phrase is not repeated, caps links per article, and
never links to the post itself or to a URL already used.
"""

import re

from ..cortex.lexicon import loader
from ..cortex.semantic.similarity import token_similarity
from ..cortex.text.normalize import squish
from ..cortex.text.stopwords import content_words, is_stopword
from ..cortex.text.tokenize import words

MAX_LINKS = 5
MIN_RELEVANCE = 0.14
_ANCHOR_STOP = re.compile(r"^(read more|click here|this article|here|link|more|source)$", re.I)


def relevance(article_text: str, candidate_title: str, *, keywords: list[str] | None = None) -> float:
    """0..1 relevance of a published post to this article."""
    keywords = keywords or []
    title_tokens = set(content_words(words(candidate_title)))
    if not title_tokens:
        return 0.0
    body_tokens = set(content_words(words(article_text)))
    overlap = len(title_tokens & body_tokens) / len(title_tokens)
    keyword_hits = sum(1 for keyword in keywords
                       if keyword.lower() in candidate_title.lower()) / max(1, len(keywords))
    exact = token_similarity(candidate_title, article_text[:600])
    return round(min(1.0, 0.55 * overlap + 0.3 * keyword_hits + 0.15 * exact), 4)


def rank_candidates(article_text: str, posts: list[dict], *, keywords: list[str] | None = None,
                    self_url: str = "", limit: int = MAX_LINKS) -> list[dict]:
    """Best internal-link targets, already scored and de-duplicated."""
    keywords = keywords or []
    scored: list[dict] = []
    seen_urls: set[str] = set()
    for post in posts:
        url = squish(str(post.get("url", "")))
        title = squish(str(post.get("title", "")))
        if not url or not title or url in seen_urls:
            continue
        if self_url and (url == self_url or url.rstrip("/") == self_url.rstrip("/")):
            continue
        value = relevance(article_text, title, keywords=keywords)
        if value < MIN_RELEVANCE:
            continue
        seen_urls.add(url)
        scored.append({"url": url, "title": title, "relevance": value,
                       "anchor": anchor_for(title, article_text, keywords=keywords)})
    scored.sort(key=lambda item: (-item["relevance"], item["title"]))
    return scored[:limit]


def anchor_for(title: str, article_text: str = "", *, keywords: list[str] | None = None,
               used: list[str] | None = None) -> str:
    """Descriptive anchor text: the post title, trimmed and never a bare "read more"."""
    keywords = keywords or []
    used = [item.lower() for item in (used or [])]
    candidates = [squish(title)]
    for keyword in keywords:
        if keyword.lower() in title.lower() and len(keyword.split()) > 1:
            candidates.insert(0, keyword.title())
    for template in loader.anchor_templates():
        try:
            candidates.append(squish(template.format(title=title)))
        except (KeyError, IndexError):
            continue
    for candidate in candidates:
        text = candidate.strip(" .,:-")
        if not text or _ANCHOR_STOP.match(text):
            continue
        if text.lower() in used:
            continue
        if len(text.split()) > 9:
            text = " ".join(text.split()[:8]).rstrip(" ,;:-")
        return text
    return squish(title)[:70] or "related coverage"


def rotation(anchors: list[str]) -> float:
    """0..1 anchor-text variety: repeated anchors look manipulative."""
    if len(anchors) < 2:
        return 1.0
    lowered = [squish(item).lower() for item in anchors]
    return round(len(set(lowered)) / len(lowered), 3)


def contextual_anchor(title: str, article_text: str, *, max_words: int = 4) -> str:
    """The longest run of words shared by the target title and this article.

    A contextual anchor ("remittance transfers") reads naturally and can actually be
    placed in the body, while the target's own headline appears nowhere in it.
    """
    title_tokens = [token for token in words(title) if not is_stopword(token)]
    body = squish(article_text)
    lowered = body.lower()
    best = ""
    for start in range(len(title_tokens)):
        for end in range(len(title_tokens), start, -1):
            if end - start > max_words:
                continue
            phrase = " ".join(title_tokens[start:end])
            if len(phrase) < 6:
                continue
            index = lowered.find(phrase)
            if index >= 0 and len(phrase) > len(best):
                best = body[index:index + len(phrase)]
    return squish(best)


def insert(html: str, links: list[dict], *, per_paragraph: int = 1) -> tuple[str, list[dict]]:
    """Add the links into the body, one per paragraph, first mention only.

    Only plain paragraph text is touched: headings, quotes, tables, existing links
    and the source list are left alone, so the markup stays valid.
    """
    if not links or not html:
        return html, []
    queue = [dict(item) for item in links if item.get("url") and item.get("anchor")]
    placed: list[dict] = []
    paragraphs = re.split(r"(?s)(<p\b[^>]*>.*?</p>)", html)
    for index, chunk in enumerate(paragraphs):
        if not queue or not chunk.startswith("<p"):
            continue
        if any(tag in chunk for tag in ("<blockquote", "<h1", "<h2", "<h3", "<table", "<a ")):
            continue
        added_here = 0
        for link in list(queue):
            if added_here >= per_paragraph:
                break
            anchor = link.get("contextual") or link["anchor"]
            pattern = re.compile(rf"(?<![<\\w]){re.escape(anchor)}(?![\\w>])", re.IGNORECASE)
            match = pattern.search(chunk)
            if not match:
                words_found = anchor.split()
                if len(words_found) > 2:
                    continue
                pattern = re.compile(rf"(?<![<\\w]){re.escape(words_found[0])}(?![\\w>])", re.I)
                match = pattern.search(chunk)
                if not match:
                    continue
                anchor = match.group(0)
            href = link["url"]
            chunk = (chunk[: match.start()] +
                     f'<a href="{href}" title="{_escape(anchor)}" rel="bookmark">{_escape(anchor)}</a>' +
                     chunk[match.end():])
            queue.remove(link)
            placed.append({**link, "anchor": anchor})
            added_here += 1
        paragraphs[index] = chunk
    return "".join(paragraphs), placed


def related_box(posts: list[dict], *, title: str = "Related coverage") -> str:
    """A visible related-articles block (also a crawl path for new posts)."""
    items = [post for post in posts if post.get("url") and post.get("title")][:5]
    if not items:
        return ""
    rows = "".join(f'<li><a href="{_escape(post["url"])}" rel="bookmark">'
                   f'{_escape(post.get("anchor") or post["title"])}</a></li>' for post in items)
    return f'<div class="bsd-related"><h3>{_escape(title)}</h3><ul>{rows}</ul></div>'


def outgoing_links(html: str) -> list[dict]:
    """Every link in the body, split into internal and external for the audit."""
    out = []
    for match in re.finditer(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html or "", re.S | re.I):
        url, text = match.group(1), squish(re.sub(r"<[^>]+>", "", match.group(2)))
        out.append({"url": url, "anchor": text,
                    "external": bool(re.match(r"https?://", url)) and "blogspot" not in url,
                    "nofollow": "nofollow" in match.group(0)})
    return out


def _escape(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
