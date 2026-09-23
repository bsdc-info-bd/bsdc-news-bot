"""RSS/Atom ingestion: parallel fetch, per-feed isolation, normalisation."""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

import feedparser

from .http import HttpClient
from .log import get_logger
from .settings import Feed
from .utils import (
    absolutize,
    canonical_url,
    from_struct_time,
    host_of,
    is_http_url,
    normalize_space,
    parse_iso,
    strip_tags,
)

log = get_logger("feeds")


@dataclass
class FeedItem:
    title: str
    url: str
    source: str
    source_url: str
    category: str
    published: datetime | None
    summary: str = ""
    author: str = ""
    image: str = ""
    tags: list[str] = field(default_factory=list)
    feed_weight: float = 1.0
    language: str = "en"
    score: float = 0.0
    score_notes: list[str] = field(default_factory=list)
    cluster_size: int = 1
    related_sources: list[str] = field(default_factory=list)

    @property
    def canonical(self) -> str:
        return canonical_url(self.url)

    @property
    def host(self) -> str:
        return host_of(self.url)


@dataclass
class FeedResult:
    feed: Feed
    items: list[FeedItem]
    error: str = ""
    status: int = 0


def _entry_image(entry, base: str) -> str:
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key, []) or []:
            url = absolutize(media.get("url"), base)
            medium = (media.get("medium") or media.get("type") or "image").lower()
            if url and ("image" in medium or re.search(r"\.(jpe?g|png|webp|avif)(\?|$)", url, re.I)):
                return url
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image"):
            url = absolutize(link.get("href"), base)
            if url:
                return url
    for block in [entry.get("summary", "")] + [c.get("value", "") for c in entry.get("content", []) or []]:
        match = re.search(r"<img[^>]+src=[\"']([^\"']+)", block or "", re.I)
        if match:
            url = absolutize(html.unescape(match.group(1)), base)
            if url:
                return url
    return ""


def _resolve_link(entry) -> str:
    link = entry.get("link") or ""
    # FeedBurner / Google News originals
    for key in ("feedburner_origlink", "origlink"):
        if entry.get(key):
            link = entry[key]
    if not is_http_url(link):
        for alt in entry.get("links", []) or []:
            if alt.get("rel") in (None, "alternate") and is_http_url(alt.get("href")):
                link = alt["href"]
                break
    return link.strip()


def parse_feed(content: bytes | str, feed: Feed) -> list[FeedItem]:
    parsed = feedparser.parse(content)
    source = normalize_space(feed.name or parsed.feed.get("title") or host_of(feed.url) or "News")
    source_url = parsed.feed.get("link") or feed.url
    items: list[FeedItem] = []
    for entry in parsed.entries[: max(1, feed.max_items)]:
        title = normalize_space(html.unescape(strip_tags(entry.get("title", ""))))
        link = _resolve_link(entry)
        if not title or not is_http_url(link):
            continue
        published = (from_struct_time(entry.get("published_parsed"))
                     or from_struct_time(entry.get("updated_parsed"))
                     or parse_iso(entry.get("published") or entry.get("updated")))
        summary = strip_tags(entry.get("summary", ""))[:1200]
        tags = [normalize_space(t.get("term", "")) for t in entry.get("tags", []) or [] if t.get("term")]
        items.append(FeedItem(
            title=title,
            url=link,
            source=source,
            source_url=source_url,
            category=feed.category,
            published=published,
            summary=summary,
            author=normalize_space(entry.get("author", "")),
            image=_entry_image(entry, link),
            tags=tags[:10],
            feed_weight=feed.weight,
            language=feed.language,
        ))
    return items


class FeedFetcher:
    """Fetches every feed in parallel.  Deliberately *no* conditional GET (ETag/304):
    a 304 would hide items that were not published last run because the budget ran out."""

    def __init__(self, http: HttpClient, workers: int = 6) -> None:
        self.http = http
        self.workers = workers

    def fetch_one(self, feed: Feed) -> FeedResult:
        headers = {"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"}
        try:
            resp = self.http.get(feed.url, headers=headers, timeout=20)
        except Exception as exc:
            return FeedResult(feed, [], error=f"network error: {_short_error(exc)}")
        if resp.status_code >= 400:
            return FeedResult(feed, [], error=f"HTTP {resp.status_code}", status=resp.status_code)
        try:
            items = parse_feed(resp.content, feed)
        except Exception as exc:  # malformed feed should never break the run
            return FeedResult(feed, [], error=f"parse error: {exc}", status=resp.status_code)
        if not items:
            return FeedResult(feed, [], error="feed returned no usable entries", status=resp.status_code)
        return FeedResult(feed, items, status=resp.status_code)

    def fetch_all(self, feeds: list[Feed]) -> list[FeedResult]:
        active = [f for f in feeds if f.enabled]
        results: list[FeedResult] = []
        with ThreadPoolExecutor(max_workers=max(1, min(self.workers, len(active) or 1))) as pool:
            futures = {pool.submit(self.fetch_one, f): f for f in active}
            for future in as_completed(futures):
                feed = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # defensive
                    results.append(FeedResult(feed, [], error=str(exc)))
        order = {f.url: i for i, f in enumerate(active)}
        results.sort(key=lambda r: order.get(r.feed.url, 0))
        failed = 0
        for res in results:
            if res.error:
                failed += 1
                log.info("   ✗ %-28s %s", (res.feed.name or host_of(res.feed.url))[:28], res.error)
            else:
                log.info("   ✓ %-28s %2d items", (res.feed.name or host_of(res.feed.url))[:28], len(res.items))
        if results and failed > len(results) / 2:
            log.warning("%d of %d feeds failed — check the feed URLs or network", failed, len(results))
        return results


def _short_error(exc: Exception) -> str:
    text = str(exc)
    for marker in ("SSLError", "ConnectTimeout", "ReadTimeout", "NameResolution", "ConnectionRefused"):
        if marker in text:
            return marker
    return text[:160]
