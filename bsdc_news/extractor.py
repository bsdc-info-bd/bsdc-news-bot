"""Article extraction: clean text (trafilatura → JSON-LD → paragraph fallback),
metadata (author, date, canonical, description, keywords, paywall flag) and
a ranked list of *relevant* images (og:image first, junk filtered out)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .errors import ExtractionError
from .http import HttpClient
from .log import get_logger
from .utils import absolutize, canonical_url, dedupe_keep_order, normalize_space, strip_tags, word_count

log = get_logger("extractor")

try:
    import trafilatura
    from trafilatura import bare_extraction
except Exception:  # pragma: no cover - trafilatura is a hard requirement in production
    trafilatura = None
    bare_extraction = None

# Substrings that always indicate a non-editorial image
JUNK_IMAGE_MARKERS = (
    "/ads/", "adserver", "doubleclick", "banner-ad", "1x1", "spacer.", "blank.gif", "gravatar", "favicon",
    "sprite", "feedburner", "/assets/brand", "wp-includes", "data:image", ".svg", ".gif",
)
# Whole path tokens (split on non-alphanumerics) — avoids false positives such as
# "social-media-ban.jpg" or "downloading-app.jpg" that a substring test would reject.
JUNK_IMAGE_TOKENS = frozenset({
    "avatar", "avatars", "logo", "logos", "icon", "icons", "badge", "badges", "button", "buttons",
    "tracker", "tracking", "pixel", "emoji", "placeholder", "lazyload", "headshot", "headshots",
    "profile", "profiles", "author", "authors", "newsletter", "subscribe", "sponsor", "sponsored",
    "advert", "advertisement", "thumbnail-small", "mugshot",
})
GOOD_IMAGE_EXT = re.compile(r"\.(jpe?g|png|webp|avif)(?:[?#]|$)", re.I)
PAYWALL_MARKERS = ("subscribe to continue", "subscribers only", "to continue reading", "paywall",
                   "already a subscriber", "sign in to read", "this article is for subscribers")


@dataclass
class ImageCandidate:
    url: str
    alt: str = ""
    caption: str = ""
    credit: str = ""
    width: int = 0
    height: int = 0
    origin: str = "page"  # og | jsonld | feed | article | page | openverse
    score: float = 0.0
    license: str = ""
    license_url: str = ""
    creator: str = ""
    source_page: str = ""


@dataclass
class Article:
    url: str
    final_url: str = ""
    title: str = ""
    text: str = ""
    html_paragraphs: list[str] = field(default_factory=list)
    author: str = ""
    published: str = ""
    modified: str = ""
    sitename: str = ""
    description: str = ""
    language: str = ""
    canonical: str = ""
    keywords: list[str] = field(default_factory=list)
    images: list[ImageCandidate] = field(default_factory=list)
    paywalled: bool = False
    status: int = 0

    @property
    def words(self) -> int:
        return word_count(self.text)


def _int(value) -> int:
    try:
        return int(re.sub(r"[^\d]", "", str(value))[:5] or 0)
    except ValueError:
        return 0


def _best_from_srcset(srcset: str, base: str) -> tuple[str, int]:
    best, best_w = "", 0
    for part in (srcset or "").split(","):
        bits = part.strip().split()
        if not bits:
            continue
        width = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            width = _int(bits[1])
        url = absolutize(bits[0], base)
        if url and width >= best_w:
            best, best_w = url, width
    return best, best_w


def _is_junk(url: str, alt: str = "") -> bool:
    low = url.lower()
    if any(marker in low for marker in JUNK_IMAGE_MARKERS):
        return True
    path = re.sub(r"^https?://[^/]+", "", low).split("?", 1)[0]
    if JUNK_IMAGE_TOKENS & set(re.split(r"[^a-z0-9]+", path)):
        return True
    if re.search(r"[?&/](w|width)=?(\d{1,2})(?:\D|$)", low):  # tiny thumbnails such as w=40
        return True
    return bool(re.search(r"\b(logo|avatar|icon)\b", (alt or "").lower()))


def _jsonld_objects(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for tag in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, dict):
                if "@graph" in obj and isinstance(obj["@graph"], list):
                    stack.extend(obj["@graph"])
                out.append(obj)
            elif isinstance(obj, list):
                stack.extend(obj)
    return out


def _types(obj: dict) -> set[str]:
    t = obj.get("@type", "")
    return {str(x).lower() for x in (t if isinstance(t, list) else [t])}


ARTICLE_TYPES = {"newsarticle", "article", "reportagenewsarticle", "blogposting", "techarticle",
                 "analysisnewsarticle", "reviewnewsarticle"}


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return normalize_space(tag["content"])
    return ""


def collect_images(soup: BeautifulSoup, base: str, jsonld: list[dict], limit: int = 12) -> list[ImageCandidate]:
    cands: list[ImageCandidate] = []

    og = _meta(soup, "og:image:secure_url", "og:image", "twitter:image", "twitter:image:src")
    if og:
        url = absolutize(og, base)
        if url and not _is_junk(url):
            cands.append(ImageCandidate(url=url, origin="og",
                                        width=_int(_meta(soup, "og:image:width")),
                                        height=_int(_meta(soup, "og:image:height")),
                                        alt=_meta(soup, "og:image:alt", "twitter:image:alt")))

    for obj in jsonld:
        if not (_types(obj) & ARTICLE_TYPES):
            continue
        imgs = obj.get("image")
        for img in imgs if isinstance(imgs, list) else [imgs]:
            if isinstance(img, dict):
                url = absolutize(img.get("url") or img.get("contentUrl"), base)
                if url and not _is_junk(url):
                    cands.append(ImageCandidate(url=url, origin="jsonld", width=_int(img.get("width")),
                                                height=_int(img.get("height")),
                                                caption=normalize_space(img.get("caption", ""))[:200]))
            elif isinstance(img, str):
                url = absolutize(img, base)
                if url and not _is_junk(url):
                    cands.append(ImageCandidate(url=url, origin="jsonld"))

    scope = soup.find("article") or soup.find(attrs={"itemprop": "articleBody"}) or soup.find("main") or soup
    for node in scope.find_all(["figure", "img", "picture"]):
        img = node if node.name == "img" else node.find("img")
        if img is None:
            continue
        width = _int(img.get("width"))
        url = ""
        for attr in ("data-src", "data-lazy-src", "data-original", "data-url", "src"):
            val = img.get(attr)
            if val and not str(val).startswith("data:"):
                url = absolutize(val, base)
                if url:
                    break
        srcset = img.get("srcset") or img.get("data-srcset")
        if not srcset:
            source = node.find("source") if node.name in ("picture", "figure") else None
            srcset = source.get("srcset") if source else ""
        if srcset:
            best, best_w = _best_from_srcset(srcset, base)
            if best and best_w >= width:
                url, width = best, best_w
        if not url:
            continue
        alt = normalize_space(img.get("alt", ""))[:200]
        if _is_junk(url, alt):
            continue
        fig = img.find_parent("figure")
        caption = credit = ""
        if fig is not None:
            cap = fig.find("figcaption")
            if cap:
                caption = normalize_space(cap.get_text(" "))[:240]
                m = re.search(r"(?:credit|image|photo|source)\s*:?\s*([^|]{2,80})$", caption, re.I)
                if m:
                    credit = m.group(1).strip()
        cands.append(ImageCandidate(url=url, alt=alt, caption=caption, credit=credit, width=width,
                                    height=_int(img.get("height")),
                                    origin="article" if scope is not soup else "page"))

    uniq = dedupe_keep_order(cands, key=lambda c: re.sub(r"[?#].*$", "", c.url))
    for c in uniq:
        c.score = score_image(c)
    uniq.sort(key=lambda c: c.score, reverse=True)
    return uniq[:limit]


def score_image(c: ImageCandidate) -> float:
    score = {"og": 40, "jsonld": 35, "feed": 30, "article": 20, "page": 5, "openverse": 15}.get(c.origin, 0)
    if GOOD_IMAGE_EXT.search(c.url):
        score += 5
    if c.width:
        score += 15 if c.width >= 1000 else 8 if c.width >= 600 else -25 if c.width < 300 else 0
    if c.width and c.height:
        ratio = c.width / max(1, c.height)
        if ratio < 0.6 or ratio > 3.2:
            score -= 20  # skyscraper / banner shapes
    if c.caption:
        score += 4
    if c.alt:
        score += 2
    return score


def _jsonld_fields(jsonld: list[dict]) -> dict:
    for obj in jsonld:
        if _types(obj) & ARTICLE_TYPES:
            author = obj.get("author")
            if isinstance(author, list):
                author = author[0] if author else ""
            if isinstance(author, dict):
                author = author.get("name", "")
            body = obj.get("articleBody") or ""
            kw = obj.get("keywords") or []
            if isinstance(kw, str):
                kw = [k.strip() for k in kw.split(",")]
            return {
                "headline": normalize_space(obj.get("headline", "")),
                "author": normalize_space(str(author or "")),
                "published": str(obj.get("datePublished", "") or ""),
                "modified": str(obj.get("dateModified", "") or ""),
                "description": normalize_space(obj.get("description", "")),
                "body": normalize_space(strip_tags(body)) if isinstance(body, str) else "",
                "keywords": [normalize_space(k) for k in kw if isinstance(k, str) and k.strip()][:15],
                "free": obj.get("isAccessibleForFree"),
            }
    return {}


def _fallback_paragraphs(soup: BeautifulSoup) -> list[str]:
    scope = soup.find("article") or soup.find(attrs={"itemprop": "articleBody"}) or soup.find("main") or soup.body
    if scope is None:
        return []
    for bad in scope.find_all(["script", "style", "nav", "aside", "footer", "form", "noscript", "iframe"]):
        bad.decompose()
    paras = []
    for p in scope.find_all("p"):
        text = normalize_space(p.get_text(" "))
        if word_count(text) >= 8 and not re.search(r"(cookie|subscribe|newsletter|sign up|advertis)", text, re.I):
            paras.append(text)
    return paras


def clean_text(text: str) -> str:
    """Remove boiler-plate lines that extraction sometimes leaves behind."""
    lines = []
    for line in normalize_space(text).split("\n"):
        low = line.lower().strip()
        if not low:
            continue
        if re.match(r"^(advertisement|related:|read more|see also|sign up|subscribe|share this|"
                    r"follow us|image credit|photo credit|getty images|© ?\d{4}|all rights reserved)", low):
            continue
        if len(low) < 25 and low.endswith(":"):
            continue
        lines.append(line.strip())
    return "\n".join(lines)


def parse_article(html_text: str, url: str, final_url: str = "", max_images: int = 12) -> Article:
    base = final_url or url
    soup = BeautifulSoup(html_text, "lxml")
    jsonld = _jsonld_objects(soup)
    ld = _jsonld_fields(jsonld)
    art = Article(url=url, final_url=base)

    text = ""
    if bare_extraction is not None:
        try:
            # deduplicate=False: trafilatura's dedup uses a process-wide LRU cache and would
            # silently discard a page that was already extracted once in this process.
            doc = bare_extraction(html_text, url=base, with_metadata=True, favor_precision=True,
                                  include_comments=False, include_tables=False, deduplicate=False)
        except Exception as exc:
            log.debug("trafilatura failed on %s: %s", url, exc)
            doc = None
        if doc is not None:
            text = getattr(doc, "text", "") or ""
            art.title = normalize_space(getattr(doc, "title", "") or "")
            art.author = normalize_space(getattr(doc, "author", "") or "")
            art.published = str(getattr(doc, "date", "") or "")
            art.sitename = normalize_space(getattr(doc, "sitename", "") or "")
            art.description = normalize_space(getattr(doc, "description", "") or "")
            art.language = str(getattr(doc, "language", "") or "")
            tags = getattr(doc, "tags", None) or []
            art.keywords = [normalize_space(t) for t in tags if t][:15]

    if word_count(text) < 150 and word_count(ld.get("body", "")) > word_count(text):
        text = ld["body"]
    if word_count(text) < 150:
        paras = _fallback_paragraphs(BeautifulSoup(html_text, "lxml"))
        if word_count("\n".join(paras)) > word_count(text):
            text = "\n".join(paras)

    art.text = clean_text(text)
    art.title = art.title or ld.get("headline") or _meta(soup, "og:title", "twitter:title") or (
        normalize_space(soup.title.get_text()) if soup.title else "")
    art.author = art.author or ld.get("author", "") or _meta(soup, "author", "article:author")
    art.published = art.published or ld.get("published", "") or _meta(soup, "article:published_time")
    art.modified = ld.get("modified", "") or _meta(soup, "article:modified_time", "og:updated_time")
    art.sitename = art.sitename or _meta(soup, "og:site_name", "application-name")
    art.description = art.description or ld.get("description", "") or _meta(
        soup, "og:description", "description", "twitter:description")
    art.keywords = art.keywords or ld.get("keywords", []) or [
        k.strip() for k in _meta(soup, "news_keywords", "keywords").split(",") if k.strip()][:15]
    html_tag = soup.find("html")
    art.language = art.language or (html_tag.get("lang", "") if html_tag else "")
    link = soup.find("link", attrs={"rel": "canonical"})
    art.canonical = absolutize(link.get("href"), base) if link and link.get("href") else canonical_url(base)
    art.images = collect_images(soup, base, jsonld, limit=max_images)
    head = html_text[:200000].lower()
    art.paywalled = ld.get("free") in (False, "False", "false") or any(m in head for m in PAYWALL_MARKERS)
    art.html_paragraphs = [p for p in art.text.split("\n") if p.strip()]
    return art


class Extractor:
    def __init__(self, http: HttpClient, settings) -> None:
        self.http = http
        self.min_words = int(settings.get("extraction.min_words", 180))
        self.timeout = float(settings.get("extraction.timeout", 20))
        self.max_images = int(settings.get("extraction.max_images", 4)) * 3

    def extract(self, url: str) -> Article:
        if not self.http.allowed(url):
            raise ExtractionError("blocked by robots.txt", permanent=True)
        resp = self.http.fetch_html(url, timeout=self.timeout)
        if resp.status_code in (404, 410):
            raise ExtractionError(f"HTTP {resp.status_code}", permanent=True)
        if resp.status_code != 200 or not resp.text:
            raise ExtractionError(f"HTTP {resp.status_code or 'network error'}")
        ctype = (resp.headers or {}).get("Content-Type", "text/html")
        if "html" not in ctype and "xml" not in ctype:
            raise ExtractionError(f"not an HTML page ({ctype})", permanent=True)
        art = parse_article(resp.text, url, resp.url or url, max_images=self.max_images)
        art.status = resp.status_code
        final_host = urlsplit(art.final_url).netloc
        if final_host and final_host != urlsplit(url).netloc:
            log.debug("Redirected %s -> %s", url, art.final_url)
        return art


# Backwards compatible helper (old scraper.scrape_article_data signature)
def extract_text_and_images(html_text: str, url: str) -> tuple[str | None, list[str]]:
    art = parse_article(html_text, url)
    return (art.text or None), [c.url for c in art.images]
