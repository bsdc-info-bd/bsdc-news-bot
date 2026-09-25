"""Final assembly: written sections plus SEO blocks become one HTML document.

The renderer only needs `body_html`, so every structural decision — heading levels,
bullet markup, blockquotes, the TL;DR box, FAQ markup and the source block — is
made here. Output is XHTML-clean and safe for Blogger's post body.
"""

import html
import re

from ..types import Section
from .sections import WrittenSection
from .tldr import build as build_tldr

_SAFE_ATTR = re.compile(r'[\s"\'<>]')


def esc(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


def tldr_block(facts: list, *, lede: str = "") -> str:
    items = build_tldr(facts, lede=lede)
    if not items:
        return ""
    body = "".join(f"<li>{esc(item)}</li>" for item in items)
    return (f'<div class="bsd-tldr"><p class="bsd-tldr-title">Key points</p>'
            f'<ul>{body}</ul></div>')


def bullets_block(items: list[str], *, title: str = "At a glance") -> str:
    items = [item for item in items if item]
    if not items:
        return ""
    body = "".join(f"<li>{esc(item)}</li>" for item in items)
    heading = f'<p class="bsd-list-title">{esc(title)}</p>' if title else ""
    return f'<div class="bsd-bullets">{heading}<ul>{body}</ul></div>'


def specs_block(rows: list[tuple[str, str]], *, title: str = "") -> str:
    rows = [(label, value) for label, value in rows if label and value]
    if not rows:
        return ""
    body = "".join(f"<tr><th scope=\"row\">{esc(label)}</th><td>{esc(value)}</td></tr>"
                   for label, value in rows)
    caption = f"<caption>{esc(title)}</caption>" if title else ""
    return (f'<div class="bsd-specs"><table class="bsd-table">{caption}'
            f'<tbody>{body}</tbody></table></div>')


def quote_block(text: str, speaker: str = "") -> str:
    if not text:
        return ""
    attribution = f'<footer>&mdash; {esc(speaker)}</footer>' if speaker else ""
    return f'<blockquote class="bsd-quote"><p>{esc(text)}</p>{attribution}</blockquote>'


def faq_block(items: list[tuple[str, str]]) -> str:
    items = [(question, answer) for question, answer in items if question and answer]
    if not items:
        return ""
    body = "".join(
        f'<div class="bsd-faq-item"><h3>{esc(question)}</h3><p>{esc(answer)}</p></div>'
        for question, answer in items)
    return f'<div class="bsd-faq"><h2>Frequently asked questions</h2>{body}</div>'


def section_html(written: WrittenSection, *, level: int = 2) -> str:
    """One section: heading, paragraphs, then any lists or quotes it carries."""
    if not (written.paragraphs or written.bullets or written.specs or written.quotes):
        return ""                          # never render a heading with nothing under it
    parts: list[str] = []
    if written.heading:
        parts.append(f"<h{level}>{esc(written.heading)}</h{level}>")
    for paragraph in written.paragraphs:
        parts.append(f"<p>{esc(paragraph)}</p>")
    if written.specs:
        parts.append(specs_block(written.specs))
    if written.bullets:
        parts.append(bullets_block(written.bullets))
    for text, speaker in written.quotes:
        parts.append(quote_block(text, speaker))
    return "".join(parts)


def compose(*, lede: str, sections: list[WrittenSection], tldr: str = "",
            faq: list[tuple[str, str]] | None = None, source_block: str = "",
            disclosure: str = "", credibility: str = "", outlook: str = "",
            internal_links_html: str = "") -> str:
    """Assemble the complete article body in reading order."""
    parts: list[str] = []
    if lede:
        parts.append(f'<p class="bsd-lede">{esc(lede)}</p>')
    if tldr:
        parts.append(tldr)
    for written in sections:
        block = section_html(written)
        if block:
            parts.append(block)
    if outlook:
        parts.append(outlook)
    if faq:
        parts.append(faq_block(faq))
    if internal_links_html:
        parts.append(internal_links_html)
    if credibility:
        parts.append(credibility)
    if source_block:
        parts.append(source_block)
    if disclosure:
        parts.append(disclosure)
    return "".join(parts)


def to_sections(written: list[WrittenSection], *, lede: str = "") -> list[Section]:
    """The structured `Section` records the draft carries for rendering/reuse."""
    out: list[Section] = []
    if lede:
        out.append(Section(heading="", paragraphs=[lede], kind="lede"))
    for item in written:
        out.append(Section(heading=item.heading, paragraphs=list(item.paragraphs),
                           bullets=list(item.bullets), kind=item.kind or "body"))
    return out


def plain_text(html_body: str) -> str:
    """HTML to text — used for word counts, social cards and notifications."""
    text = re.sub(r"(?s)<(script|style|table)[^>]*>.*?</\1>", " ", html_body or "")
    text = re.sub(r"</(p|h[1-6]|li|blockquote|div)>", "\n", text)
    text = re.sub(r"<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def word_count(html_body: str) -> int:
    return len(plain_text(html_body).split())


def anchors_used(html_body: str) -> list[str]:
    """Anchor text of every in-body link, for internal-link auditing."""
    return [html.unescape(text).strip() for text in re.findall(r"<a[^>]*>(.*?)</a>", html_body or "", re.S)]


_BOILERPLATE = ("bsd-sources", "bsd-disclosure", "bsd-credibility", "bsd-accessed")


def prose_only(html_body: str) -> str:
    """The article prose: no source list, no disclosure, no blockquoted speech.

    House-style and readability checks are about our own writing, so quoted material
    and the fixed attribution blocks are removed before measuring.
    """
    out = html_body or ""
    for name in _BOILERPLATE:
        out = re.sub(rf'(?s)<div class="{name}".*?</div>', " ", out)
        out = re.sub(rf'(?s)<p class="{name}".*?</p>', " ", out)
    out = re.sub(r"(?s)<blockquote.*?</blockquote>", " ", out)
    out = re.sub(r"(?s)<tfoot.*?</tfoot>", " ", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def prose_text(html_body: str) -> str:
    """Plain text of the article prose only."""
    return plain_text(prose_only(html_body))
