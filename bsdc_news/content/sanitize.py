"""Whitelist HTML sanitiser for model output (XSS-safe, Blogger-friendly)."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, NavigableString

from ..utils import is_http_url, normalize_space

ALLOWED_TAGS = {
    "p", "h2", "h3", "h4", "ul", "ol", "li", "strong", "b", "em", "i", "blockquote", "mark",
    "table", "thead", "tbody", "tr", "th", "td", "br", "a", "figure", "figcaption", "img", "code", "pre",
    "sup", "sub", "hr", "div", "span",
}
ALLOWED_ATTRS = {
    "a": {"href", "rel", "target", "title", "class"},
    "img": {"src", "alt", "width", "height", "loading", "decoding", "fetchpriority", "style"},
    "th": {"scope", "colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
    "figure": {"style"},
    "figcaption": {"style"},
    "div": {"style", "class"},
    "span": {"style", "class"},
    "blockquote": {"cite"},
}
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "form", "input", "button",
                     "noscript", "svg", "math", "link", "meta", "head", "title", "select", "textarea"}
HEADING_DEMOTE = {"h1": "h2", "h5": "h4", "h6": "h4"}
SAFE_STYLE = re.compile(r"^[\w\s:;#%,.()\-/'\"]*$")


def sanitize_html(markup: str, allow_links: bool = True, allow_images: bool = False) -> str:
    if not markup:
        return ""
    markup = re.sub(r"^```(?:html)?|```$", "", markup.strip(), flags=re.I | re.M)
    soup = BeautifulSoup(markup, "lxml")
    root = soup.body or soup

    for node in root.find_all(string=lambda s: isinstance(s, Comment)):
        node.extract()
    for tag in root.find_all(list(DROP_WITH_CONTENT)):
        tag.decompose()

    for tag in list(root.find_all(True)):
        if tag.parent is None:
            continue
        name = tag.name.lower()
        if name in HEADING_DEMOTE:
            tag.name = name = HEADING_DEMOTE[name]
        if name in ("html", "body"):
            tag.unwrap()
            continue
        if name not in ALLOWED_TAGS or (name == "img" and not allow_images):
            tag.unwrap()
            continue
        if name == "a" and not allow_links:
            tag.unwrap()
            continue
        allowed = ALLOWED_ATTRS.get(name, set())
        for attr in list(tag.attrs):
            value = tag.attrs[attr]
            if attr not in allowed or attr.startswith("on"):
                del tag.attrs[attr]
                continue
            text_value = " ".join(value) if isinstance(value, list) else str(value)
            if attr in ("href", "src", "cite") and not is_http_url(text_value) or attr == "style" and (not SAFE_STYLE.match(text_value) or "expression" in text_value.lower()
                                      or "url(" in text_value.lower()):
                del tag.attrs[attr]
        if name == "a":
            if not tag.get("href"):
                tag.unwrap()
                continue
            tag["rel"] = "nofollow noopener"
            tag["target"] = "_blank"

    # remove empty paragraphs / headings
    for tag in root.find_all(["p", "h2", "h3", "h4", "li", "blockquote"]):
        if not normalize_space(tag.get_text()) and not tag.find("img"):
            tag.decompose()

    # wrap stray top-level text into paragraphs
    for child in list(root.children):
        if isinstance(child, NavigableString) and normalize_space(str(child)):
            p = soup.new_tag("p")
            child.replace_with(p)
            p.string = normalize_space(str(child))

    html_out = "".join(str(c) for c in root.children)
    html_out = re.sub(r"(<br\s*/?>\s*){2,}", "<br>", html_out)
    return html_out.strip()


def strip_markdown(text: str) -> str:
    """Convert stray markdown emphasis/headings the model may emit into HTML."""
    text = re.sub(r"^\s*#{2,3}\s+(.+)$", r"<h2>\1</h2>", text, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    return text
