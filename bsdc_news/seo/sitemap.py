"""Sitemap generation: standard, news and image sitemaps, plus the ping URLs.

Blogger publishes its own feeds, but a hand-built sitemap gives full control over
lastmod, changefreq, priority and the Google News publication tags — and the ping
endpoints are the free half of the indexing strategy.
"""

import re
from datetime import UTC, datetime
from urllib.parse import quote

from ..cortex.text.normalize import squish

MAX_URLS = 49000                     # stay under the 50,000-URL protocol limit
MAX_BYTES = 49 * 1024 * 1024
XSI = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_URL = "http://www.sitemaps.org/schemas/sitemap/0.9"
NEWS_SCHEMA = "http://www.google.com/schemas/sitemap-news/0.9"
IMAGE_SCHEMA = "http://www.google.com/schemas/sitemap-image/1.1"
PING_TARGETS = {
    "google": "https://www.google.com/ping?sitemap={sitemap}",
    "bing": "https://www.bing.com/ping?sitemap={sitemap}",
}


def _escape(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


def _w3c(moment: datetime | str | None) -> str:
    if isinstance(moment, datetime):
        stamp = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    else:
        stamp = datetime.now(UTC)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def priority_for(index: int, total: int, *, age_days: float = 0.0) -> str:
    """Newer and more prominent posts get a higher crawl priority."""
    if age_days <= 1:
        base = 0.9
    elif age_days <= 7:
        base = 0.8
    elif age_days <= 30:
        base = 0.6
    else:
        base = 0.4
    if total and index == 0:
        base = min(1.0, base + 0.1)
    return f"{base:.1f}"


def changefreq_for(age_days: float) -> str:
    if age_days <= 1:
        return "hourly"
    if age_days <= 7:
        return "daily"
    if age_days <= 30:
        return "weekly"
    if age_days <= 180:
        return "monthly"
    return "yearly"


def urlset(posts: list[dict], *, site_url: str = "") -> str:
    """A standard sitemap.xml document."""
    now = datetime.now(UTC)
    rows: list[str] = []
    for index, post in enumerate(posts[:MAX_URLS]):
        url = squish(str(post.get("url", "")))
        if not url:
            continue
        published = post.get("published") or post.get("updated")
        age = _age_days(published, now)
        rows.append(
            "  <url>\n"
            f"    <loc>{_escape(url)}</loc>\n"
            f"    <lastmod>{_w3c(published)}</lastmod>\n"
            f"    <changefreq>{changefreq_for(age)}</changefreq>\n"
            f"    <priority>{priority_for(index, len(posts), age_days=age)}</priority>\n"
            "  </url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="{SCHEMA_URL}" xmlns:xsi="{XSI}" '
            f'xsi:schemaLocation="{SCHEMA_URL} {SCHEMA_URL}/sitemap.xsd">\n'
            + "\n".join(rows) + "\n</urlset>\n")


def news_urlset(posts: list[dict], *, site_name: str = "bsdc news", language: str = "en",
                limit: int = 1000) -> str:
    """A Google News sitemap: only posts published in the last 48 hours belong here."""
    now = datetime.now(UTC)
    fresh = [post for post in posts if _age_days(post.get("published"), now) <= 2][:limit]
    rows: list[str] = []
    for post in fresh:
        url = squish(str(post.get("url", "")))
        title = squish(str(post.get("title", "")))
        if not url or not title:
            continue
        rows.append(
            "  <url>\n"
            "    <news:news>\n"
            "      <news:publication>\n"
            f"        <news:name>{_escape(site_name)}</news:name>\n"
            f"        <news:language>{_escape(language)}</news:language>\n"
            "      </news:publication>\n"
            "      <news:publication_date>"
            f"{_w3c(post.get('published'))}</news:publication_date>\n"
            f"      <news:title>{_escape(title)}</news:title>\n"
            "    </news:news>\n"
            f"    <loc>{_escape(url)}</loc>\n"
            "  </url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="{SCHEMA_URL}" xmlns:news="{NEWS_SCHEMA}" xmlns:xsi="{XSI}" '
            f'xsi:schemaLocation="{SCHEMA_URL} {SCHEMA_URL}/sitemap.xsd">\n'
            + "\n".join(rows) + "\n</urlset>\n")


def image_urlset(posts: list[dict], *, limit: int = 1000) -> str:
    """An image sitemap so article photos can appear in image search."""
    rows: list[str] = []
    for post in posts[:limit]:
        url = squish(str(post.get("url", "")))
        image = squish(str(post.get("image") or post.get("image_url") or ""))
        if not url or not image:
            continue
        caption = squish(str(post.get("image_caption") or post.get("title") or ""))
        rows.append(
            "  <url>\n"
            f"    <loc>{_escape(url)}</loc>\n"
            "    <image:image>\n"
            f"      <image:loc>{_escape(image)}</image:loc>\n"
            + (f"      <image:title>{_escape(caption[:100])}</image:title>\n" if caption else "")
            + (f"      <image:caption>{_escape(caption[:250])}</image:caption>\n" if caption else "")
            + "    </image:image>\n  </url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="{SCHEMA_URL}" xmlns:image="{IMAGE_SCHEMA}">\n'
            + "\n".join(rows) + "\n</urlset>\n")


def index(sitemaps: list[str], *, lastmod: datetime | None = None) -> str:
    """A sitemap index that points at several sitemap files."""
    rows = ["  <sitemap>\n"
            f"    <loc>{_escape(url)}</loc>\n"
            f"    <lastmod>{_w3c(lastmod)}</lastmod>\n  </sitemap>" for url in sitemaps if url]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<sitemapindex xmlns="{SCHEMA_URL}">\n' + "\n".join(rows) + "\n</sitemapindex>\n")


def split(posts: list[dict], *, chunk: int = MAX_URLS) -> list[list[dict]]:
    """Split a large post list into valid sitemap-sized chunks."""
    return [posts[index:index + chunk] for index in range(0, len(posts), chunk)] or [[]]


def ping_urls(sitemap_url: str) -> dict[str, str]:
    """Free ping endpoints. Both accept a public sitemap URL with no API key."""
    encoded = quote(sitemap_url, safe=":/?&=%")
    return {name: template.format(sitemap=encoded) for name, template in PING_TARGETS.items()}


def validate(document: str) -> list[str]:
    """Structural checks on a generated sitemap before it is published."""
    problems: list[str] = []
    if not document.startswith("<?xml"):
        problems.append("missing XML declaration")
    if "<loc>" not in document:
        problems.append("no <loc> entries")
    for match in re.finditer(r"<loc>\s*(.*?)\s*</loc>", document, re.S):
        url = match.group(1)
        if not url.startswith("http"):
            problems.append(f"non-absolute URL: {url[:60]}")
        if " " in url or "&" in url.replace("&amp;", ""):
            problems.append(f"unescaped or spaced URL: {url[:60]}")
    if len(document.encode("utf-8")) > MAX_BYTES:
        problems.append("document exceeds the 50MB limit")
    return problems


def _age_days(moment, now: datetime) -> float:
    if isinstance(moment, datetime):
        stamp = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        return max(0.0, (now - stamp).total_seconds() / 86400)
    return 0.0
