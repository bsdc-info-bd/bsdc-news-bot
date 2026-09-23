"""SEO helpers: headline polishing, meta descriptions, search descriptions
and schema.org JSON-LD (NewsArticle, BreadcrumbList, FAQPage)."""

from __future__ import annotations

import re

from ..utils import iso, json_for_html, normalize_space, strip_tags, truncate

SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of", "on", "or", "per",
               "the", "to", "vs", "via", "with", "from", "into", "over"}


def clean_headline(title: str, max_len: int = 100) -> str:
    title = normalize_space(strip_tags(title or ""))
    title = re.sub(r"\s*[|–—-]\s*(TechCrunch|The Verge|WIRED|Engadget|ZDNET|Ars Technica|Reuters|"
                   r"BBC News|CNN|Bloomberg|9to5\w+|Android Authority|The Register|Tom's Hardware)\s*$",
                   "", title, flags=re.I)
    title = re.sub(r"^(exclusive|breaking|update|updated)\s*[:\-–]\s*", "", title, flags=re.I)
    title = title.strip(" .\"'“”")
    if title.isupper() and len(title) > 12:
        title = title.title()
    return truncate(title, max_len, "")


def meta_description(candidate: str, fallback_text: str, limit: int = 158) -> str:
    text = normalize_space(strip_tags(candidate or ""))
    if len(text) < 70:
        text = normalize_space(strip_tags(fallback_text or ""))
    return truncate(text, limit)


def _author_type(author: str, site_name: str) -> str:
    """Desks, teams and the site itself are Organizations; anything else is a Person."""
    low = (author or "").lower()
    if not author or author == site_name or any(w in low for w in ("desk", "team", "staff", "news", "editor")):
        return "Organization"
    return "Person"


def news_article_schema(*, headline: str, description: str, images: list[str], published: str,
                        modified: str = "", url: str = "", site_name: str, site_url: str = "",
                        logo: str = "", author: str = "", section: str = "", keywords: list[str] | None = None,
                        words: int = 0, language: str = "en", source_url: str = "",
                        is_based_on_source: bool = True, author_type: str = "") -> dict:
    publisher = {"@type": "NewsMediaOrganization", "name": site_name}
    if site_url:
        publisher["url"] = site_url
    if logo:
        publisher["logo"] = {"@type": "ImageObject", "url": logo}
    data = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": truncate(headline, 110, ""),
        "description": description,
        "image": [i for i in images if i][:3],
        "datePublished": published or iso(),
        "dateModified": modified or published or iso(),
        "author": [{"@type": author_type or _author_type(author, site_name),
                    "name": author or site_name, **({"url": site_url} if site_url else {})}],
        "publisher": publisher,
        "inLanguage": language,
        "isAccessibleForFree": True,
    }
    if url:
        data["mainEntityOfPage"] = {"@type": "WebPage", "@id": url}
        data["url"] = url
    if section:
        data["articleSection"] = section
    if keywords:
        data["keywords"] = ", ".join(keywords[:10])
    if words:
        data["wordCount"] = words
    if source_url and is_based_on_source:
        data["isBasedOn"] = source_url
    return data


def breadcrumb_schema(site_name: str, site_url: str, category: str, headline: str, url: str = "") -> dict | None:
    if not site_url:
        return None
    items = [{"@type": "ListItem", "position": 1, "name": site_name, "item": site_url.rstrip("/") + "/"}]
    if category:
        items.append({"@type": "ListItem", "position": 2, "name": category,
                      "item": f"{site_url.rstrip('/')}/search/label/{category.replace(' ', '%20')}"})
    items.append({"@type": "ListItem", "position": len(items) + 1, "name": truncate(headline, 110, ""),
                  **({"item": url} if url else {})})
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}


def faq_schema(faq: list[dict]) -> dict | None:
    qa = [f for f in faq or [] if f.get("q") and f.get("a")]
    if len(qa) < 2:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": f["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in qa[:4]],
    }


def jsonld_tag(data: dict | None) -> str:
    if not data:
        return ""
    return f'<script type="application/ld+json">{json_for_html(data)}</script>'
