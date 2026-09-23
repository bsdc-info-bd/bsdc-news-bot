"""Final Blogger post HTML: hero image, reading-time bar, key takeaways box,
body with inline image, FAQ, source attribution, related posts, share buttons,
"About" footer, AI disclosure and JSON-LD schema."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote

from ..extractor import ImageCandidate
from ..images import figure_html
from ..utils import esc, iso
from .quality import reading_time
from .seo import breadcrumb_schema, faq_schema, jsonld_tag, news_article_schema

FONT = "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"


@dataclass
class RenderInput:
    headline: str
    body_html: str
    meta_description: str
    category: str
    labels: list[str]
    source_name: str
    source_url: str
    words: int
    images: list[tuple[ImageCandidate, str]] = field(default_factory=list)  # (candidate, display url)
    key_points: list[str] = field(default_factory=list)
    faq: list[dict] = field(default_factory=list)
    related_posts: list[dict] = field(default_factory=list)  # {title, url}
    related_sources: list[str] = field(default_factory=list)
    ai_generated: bool = True
    published_iso: str = ""
    source_published: str = ""
    original_author: str = ""


def _insert_after_nth(body: str, closing_tag: str, n: int, snippet: str) -> str:
    idx = -1
    for _ in range(n):
        idx = body.find(closing_tag, idx + 1)
        if idx == -1:
            return body + snippet
    cut = idx + len(closing_tag)
    return body[:cut] + snippet + body[cut:]


def key_points_box(points: list[str]) -> str:
    if not points:
        return ""
    items = "".join(f'<li style="margin:6px 0;">{esc(p)}</li>' for p in points[:5])
    return (f'<div style="margin:0 0 26px;padding:18px 22px;background:#eff6ff;border-left:5px solid #2563eb;'
            f'border-radius:10px;{FONT}">'
            f'<p style="margin:0 0 8px;font-weight:700;color:#1e3a8a;font-size:15px;">⚡ Key Takeaways</p>'
            f'<ul style="margin:0;padding-left:20px;color:#1e293b;font-size:15px;line-height:1.6;">{items}</ul></div>')


def faq_section(faq: list[dict]) -> str:
    qa = [f for f in faq or [] if f.get("q") and f.get("a")]
    if not qa:
        return ""
    blocks = "".join(
        f'<h3 style="font-size:17px;margin:18px 0 6px;">{esc(f["q"])}</h3><p>{esc(f["a"])}</p>' for f in qa[:4])
    return f'<h2>Frequently Asked Questions</h2>{blocks}'


def related_box(posts: list[dict]) -> str:
    posts = [p for p in posts if p.get("url") and p.get("title")][:4]
    if not posts:
        return ""
    items = "".join(f'<li style="margin:6px 0;"><a href="{esc(p["url"])}" style="color:#2563eb;">{esc(p["title"])}</a></li>'
                    for p in posts)
    return (f'<div style="margin-top:32px;padding:18px 22px;border:1px solid #e2e8f0;border-radius:10px;{FONT}">'
            f'<p style="margin:0 0 8px;font-weight:700;color:#0f172a;">📰 Related on this site</p>'
            f'<ul style="margin:0;padding-left:20px;font-size:15px;line-height:1.6;">{items}</ul></div>')


def share_bar(headline: str, post_url: str) -> str:
    """Plain-link share buttons (no JavaScript, works in feeds and AMP)."""
    if not post_url:
        return ""
    u, t = quote(post_url, safe=""), quote(headline[:200], safe="")
    links = [
        ("Facebook", f"https://www.facebook.com/sharer/sharer.php?u={u}"),
        ("X", f"https://twitter.com/intent/tweet?url={u}&text={t}"),
        ("WhatsApp", f"https://api.whatsapp.com/send?text={t}%20{u}"),
        ("Telegram", f"https://t.me/share/url?url={u}&text={t}"),
        ("LinkedIn", f"https://www.linkedin.com/sharing/share-offsite/?url={u}"),
        ("Reddit", f"https://www.reddit.com/submit?url={u}&title={t}"),
    ]
    btns = "".join(
        f'<a href="{esc(href)}" target="_blank" rel="noopener nofollow" '
        f'style="display:inline-block;margin:4px 6px 4px 0;padding:6px 12px;border-radius:999px;'
        f'background:#f1f5f9;color:#0f172a;text-decoration:none;font-size:13px;">{esc(name)}</a>'
        for name, href in links)
    return f'<div style="margin-top:22px;{FONT}"><span style="font-size:13px;color:#64748b;">Share: </span>{btns}</div>'


def build_post_html(inp: RenderInput, settings, post_url: str = "") -> str:
    """Render the post. Called twice by the publisher: before insert (no URL yet) and
    after insert with the real post URL, so schema + share links are self-referencing."""
    site_name = settings.site_name
    site_url = settings.get("site.url", "")
    body = inp.body_html

    hero_html = ""
    if inp.images:
        cand, url = inp.images[0]
        hero_html = figure_html(url, alt=cand.alt or inp.headline, caption=cand.caption,
                                credit=cand.credit or (inp.source_name if cand.origin != "openverse" else ""),
                                eager=True, width=cand.width, height=cand.height,
                                license_url=cand.license_url, source_page=cand.source_page)
    if len(inp.images) > 1:
        cand, url = inp.images[1]
        inline = figure_html(url, alt=cand.alt or f"{inp.headline} — detail", caption=cand.caption,
                             credit=cand.credit or inp.source_name, width=cand.width, height=cand.height,
                             license_url=cand.license_url, source_page=cand.source_page)
        body = _insert_after_nth(body, "</h2>", 1, inline) if "</h2>" in body else \
            _insert_after_nth(body, "</p>", 2, inline)

    minutes = reading_time(inp.words)
    # The first text of a Blogger post becomes its snippet (homepage cards, feeds and the
    # meta description of most templates) — so the post starts with a clean summary ("dek"),
    # and all <script> JSON-LD goes to the very end.
    dek = (f'<p class="bsdc-dek" style="font-size:19px;line-height:1.6;color:#334155;margin:0 0 18px;'
           f'{FONT}">{esc(inp.meta_description)}</p>') if inp.meta_description else ""
    info_bar = (f'<p style="{FONT}font-size:13px;color:#64748b;margin:0 0 18px;">'
                f'<span style="background:#2563eb;color:#fff;padding:2px 10px;border-radius:999px;margin-right:8px;">'
                f'{esc(inp.category or "News")}</span>⏱ {minutes} min read · Source: {esc(inp.source_name)}</p>')
    jump = "<!--more-->" if settings.get("publishing.jump_break", True) else ""

    attribution = (f'<hr style="border:0;border-top:1px solid #e2e8f0;margin:34px 0 18px;">'
                   f'<p style="font-size:13px;color:#64748b;{FONT}">'
                   f'<strong>Source:</strong> This article is based on reporting by {esc(inp.source_name)}'
                   f'{" (" + esc(inp.original_author) + ")" if inp.original_author else ""}. '
                   f'<a class="bsdc-source" href="{esc(inp.source_url)}" target="_blank" '
                   f'rel="nofollow noopener noreferrer" style="color:#64748b;text-decoration:underline;">'
                   f'Read the original article</a>.')
    if inp.related_sources:
        attribution += f' Also covered by {esc(", ".join(inp.related_sources[:4]))}.'
    attribution += "</p>"

    disclosure = ""
    if inp.ai_generated:
        disclosure = (f'<p style="font-size:12px;color:#94a3b8;{FONT}">This story was written with the help of AI '
                      f'from the cited source and reviewed by automated fact and quality checks.</p>')

    about = settings.get("site.about", "")
    footer = (f'<div style="margin-top:36px;padding:22px;background:#f8fafc;border-left:5px solid #2563eb;'
              f'border-radius:8px;{FONT}">'
              f'<h4 style="margin:0 0 8px 0;color:#1e293b;font-size:16px;">About {esc(site_name)}</h4>'
              f'<p style="margin:0;color:#475569;font-size:14px;line-height:1.6;">{esc(about)}</p></div>')

    image_urls = [u for _, u in inp.images]
    schema = news_article_schema(
        headline=inp.headline, description=inp.meta_description, images=image_urls,
        published=inp.published_iso or iso(), site_name=site_name, site_url=site_url,
        logo=settings.get("site.logo_url", ""), author=settings.get("site.author_name", site_name),
        section=inp.category, keywords=inp.labels, words=inp.words,
        language=settings.get("site.language", "en"), source_url=inp.source_url, url=post_url,
    )
    schemas = jsonld_tag(schema) + jsonld_tag(faq_schema(inp.faq)) + jsonld_tag(
        breadcrumb_schema(site_name, site_url, inp.category, inp.headline, post_url))

    article = (f'<div class="bsdc-article" style="font-size:17px;line-height:1.85;color:#1e293b;'
               f'font-family:Georgia,\'Times New Roman\',serif;">'
               f'{info_bar}{key_points_box(inp.key_points)}{body}{faq_section(inp.faq)}</div>')
    html_out = (f"{dek}\n{hero_html}\n{jump}\n{article}\n{attribution}\n{disclosure}\n"
                f"{share_bar(inp.headline, post_url)}\n{related_box(inp.related_posts)}\n{footer}\n{schemas}")
    return re.sub(r"\n{3,}", "\n\n", html_out)
