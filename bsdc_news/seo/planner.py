"""The SEO planner: one call turns a finished draft into a complete SeoPlan.

The plan holds every SEO decision — title tag, meta description, slug, canonical,
keyword set, heading outline, image alts, internal links, breadcrumbs, social cards
and the JSON-LD graph — plus the audit that scored them. The renderer only has to
paste the values in, so no SEO logic is duplicated at publish time.
"""

import re
from datetime import UTC, datetime

from ..cortex.text.normalize import squish
from ..cortex.types import ArticleDraft, SeoPlan
from . import audit as audit_mod
from . import headings as headings_mod
from . import internal_links, sitemap
from . import meta as meta_mod
from . import slug as slug_mod
from . import title as title_mod
from .schema import article as article_schema
from .schema import breadcrumb as breadcrumb_schema
from .schema import faq as faq_schema
from .schema import itemlist as itemlist_schema
from .schema import organization as organization_schema


def plan(draft: ArticleDraft, *, site_name: str = "bsdc news", site_url: str = "",
         post_url: str = "", category: str = "", author: str = "", author_url: str = "",
         publisher_logo: str = "", image_url: str = "", image_caption: str = "",
         image_credit: str = "", related: list[dict] | None = None,
         published_slugs: list[str] | None = None, published: datetime | None = None,
         language: str = "en", twitter_handle: str = "", facebook_app: str = "",
         keywords: list[str] | None = None, word_floor: int = 350,
         source_urls: list[str] | None = None, article_type: str = "NewsArticle",
         search_url: str = "") -> SeoPlan:
    """Build and audit the full SEO plan for one article."""
    related = related or []
    source_urls = [url for url in (source_urls or []) if url]
    published = published or datetime.now(UTC)
    keyword_set = dict(draft.keywords or {})
    primary = squish(str(keyword_set.get("primary", "")))
    secondary = [squish(str(item)) for item in keyword_set.get("secondary", []) if item]
    lsi = [squish(str(item)) for item in keyword_set.get("lsi", []) if item]
    entity_names = [squish(str(item)) for item in (draft.entities or []) if item]
    planned = list(dict.fromkeys([item for item in [primary, *secondary, *lsi,
                                                    *(keywords or [])] if item]))

    headline = squish(draft.headline)
    title_tag = title_mod.build(headline, keyword=primary, site_name=site_name,
                                category=category)
    description = squish(draft.meta_description) or meta_mod.description(
        lede=_lede_of(draft), dek=draft.dek, key_points=list(draft.tldr), keyword=primary)
    if not (meta_mod.MIN_LENGTH <= len(description) <= meta_mod.MAX_LENGTH):
        description = meta_mod.description(lede=_lede_of(draft), dek=draft.dek,
                                           key_points=list(draft.tldr), keyword=primary)
    slug = slug_mod.unique(slug_mod.build(headline, keyword=primary), published_slugs)
    canonical = meta_mod.canonical(post_url or site_url)

    heading_pairs = headings_mod.collect(draft.body_html)
    if not any(level == 1 for level, _ in heading_pairs):
        heading_pairs = [(1, headline), *heading_pairs]
    planned_headings = [(level, headings_mod.strengthen(text, keyword=primary,
                                                        entity=entity_names[0] if entity_names
                                                        else ""))
                        for level, text in heading_pairs]

    image_alts = [image_alt(headline, primary, image_caption, entity_names)] if image_url else []
    images = [{"url": image_url, "alt": image_alts[0]}] if image_url else []

    body_text = _text_of(draft)
    links = internal_links.rank_candidates(body_text, related, keywords=planned[:6],
                                           self_url=post_url)
    for link in links:
        link["contextual"] = internal_links.contextual_anchor(link["title"], body_text)
    body_with_links, placed = internal_links.insert(draft.body_html, links[:3])
    body_with_links = body_with_links + internal_links.related_box(links)
    if "<h1" not in body_with_links.lower():
        body_with_links = f"<h1>{headline}</h1>" + body_with_links

    faq_items = [(squish(str(question)), squish(str(answer))) for question, answer in draft.faq]
    crumbs = breadcrumb_schema.for_article(site_name=site_name, site_url=site_url,
                                           category=category, headline=headline,
                                           url=post_url or canonical)

    nodes = {
        "article": article_schema.build(
            headline=headline, description=description, url=post_url or canonical,
            images=[image_url] if image_url else [], published=published,
            modified=published, author_name=author or site_name, author_url=author_url,
            publisher_name=site_name, publisher_logo=publisher_logo, publisher_url=site_url,
            section=category, keywords=planned[:10], words=len(body_text.split()),
            language=language, article_type=article_type, caption=image_caption,
            image_credit=image_credit, same_as=[item["url"] for item in links[:3]]),
        "faq": faq_schema.build(faq_items) if faq_items else None,
        "breadcrumb": breadcrumb_schema.build(crumbs),
        "organization": organization_schema.organization(
            name=site_name, url=site_url, logo_url=publisher_logo,
            description=f"{site_name} publishes verified technology, business and "
                        "Bangladesh news, compiled from primary sources.",
            language=language, country="BD"),
        "website": organization_schema.website(
            name=site_name, url=site_url, description=description,
            search_url=search_url or (f"{site_url.rstrip('/')}/search?q={{search_term_string}}"
                                      if site_url else ""),
            language=language),
        "itemlist": itemlist_schema.related([{"url": item["url"], "title": item["title"]}
                                             for item in links]) if links else None,
    }

    published_iso = article_schema.iso(published)
    og = meta_mod.open_graph(
        title=title_tag, description=description, url=post_url or canonical,
        image=image_url, site_name=site_name, locale="en_US" if language == "en" else language,
        article_type="article", published=published_iso, modified=published_iso,
        author=author_url or author, tags=planned[:6], image_alt=image_alts[0] if image_alts else "")
    if facebook_app:
        og["fb:app_id"] = squish(facebook_app)
    twitter = meta_mod.twitter_card(title=title_tag, description=description, image=image_url,
                                    handle=twitter_handle,
                                    image_alt=image_alts[0] if image_alts else "")

    report = audit_mod.run(
        title_tag=title_tag, headline=headline, description=description, slug=slug,
        canonical=canonical, html=body_with_links, keywords=planned[:8],
        primary_keyword=primary, images=images,
        jsonld_nodes=nodes, language=language, author=author or site_name,
        published=published_iso, sources=len(source_urls), disclosure=bool(draft.machine_written),
        site_name=site_name, related_count=len(links), word_floor=word_floor)

    return SeoPlan(
        title_tag=title_tag, headline=headline, slug=slug, meta_description=description,
        canonical=canonical, primary_keyword=primary, secondary_keywords=secondary,
        lsi_keywords=lsi, entities=entity_names, headings=planned_headings,
        internal_links=[{**item, "placed": any(placed_item["url"] == item["url"]
                                               for placed_item in placed)}
                        for item in links],
        image_alts=image_alts, faq=faq_items, breadcrumbs=crumbs,
        json_ld=[node for node in nodes.values() if node],
        open_graph=og, twitter_card=twitter, score=report.score,
        checks=list(report.checks),
    )


def image_alt(headline: str, keyword: str, caption: str, entities: list[str],
              *, maximum: int = 120) -> str:
    """Descriptive alt text: what the picture shows, with the keyword if it fits."""
    base = squish(caption) or squish(headline)
    if keyword and keyword.lower() not in base.lower() and len(base) + len(keyword) < maximum:
        base = squish(f"{base} - {keyword}")
    for entity in entities[:2]:
        if entity.lower() not in base.lower() and len(base) + len(entity) < maximum:
            base = squish(f"{base} ({entity})")
            break
    return base[:maximum].rstrip(" -.,")


def _lede_of(draft: ArticleDraft) -> str:
    for section in draft.sections:
        if section.kind == "lede" and section.paragraphs:
            return squish(section.paragraphs[0])
    return compose_lede(draft.body_html)


def compose_lede(html: str) -> str:
    """The first paragraph of the rendered body."""
    match = re.search(r"(?s)<p[^>]*>(.*?)</p>", html or "")
    if not match:
        return ""
    return squish(re.sub(r"<[^>]+>", "", match.group(1)))


def _text_of(draft: ArticleDraft) -> str:
    from ..cortex.writing import compose as compose_mod

    return compose_mod.prose_text(draft.body_html)


def sitemap_entry(plan_: SeoPlan, *, url: str, published: datetime | None = None,
                  image_url: str = "", image_caption: str = "") -> dict:
    """The post record the sitemap builders consume."""
    return {"url": url or plan_.canonical, "title": plan_.headline,
            "published": published or datetime.now(UTC),
            "image": image_url, "image_caption": image_caption or plan_.headline}


def sitemap_documents(posts: list[dict], *, site_name: str = "bsdc news",
                      site_url: str = "", language: str = "en") -> dict[str, str]:
    """Standard, news and image sitemaps in one call."""
    return {
        "sitemap.xml": sitemap.urlset(posts),
        "news-sitemap.xml": sitemap.news_urlset(posts, site_name=site_name, language=language),
        "image-sitemap.xml": sitemap.image_urlset(posts),
        "sitemap-index.xml": sitemap.index([squish(site_url).rstrip("/") + name
                                            for name in ("/sitemap.xml", "/news-sitemap.xml",
                                                         "/image-sitemap.xml")] if site_url
                                           else []),
    }
