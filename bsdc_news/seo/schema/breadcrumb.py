"""BreadcrumbList structured data.

Breadcrumbs replace the raw URL in the search result, which measurably improves
click-through. The last item must not carry a link, positions must start at 1, and
every item needs an absolute URL.
"""

from ...cortex.text.normalize import squish

MAX_ITEMS = 6


def build(items: list[tuple[str, str]] | list[dict], *, link_last: bool = False) -> dict | None:
    """items are (name, url) pairs from the site root down to the article."""
    rows: list[dict] = []
    for position, item in enumerate(items or [], start=1):
        name, url = _pair(item)
        if not name:
            continue
        node: dict = {"@type": "ListItem", "position": position, "name": _clip(name)}
        if url:
            node["item"] = {"@id": squish(url), "name": _clip(name)}
        rows.append(node)
        if len(rows) >= MAX_ITEMS:
            break
    if not rows:
        return None
    if not link_last and rows:
        rows[-1].pop("item", None)         # the current page is not a link to itself
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": rows}


def _clip(name: str, limit: int = 70) -> str:
    """Trim a breadcrumb label at a word boundary.

    `squish(headline)[:70]` used to publish "…as inflation persist" — a word cut in
    half, which Google shows verbatim in the breadcrumb rich result.
    """
    text = squish(name)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-")


def _pair(item) -> tuple[str, str]:
    if isinstance(item, dict):
        return (squish(str(item.get("name") or item.get("title") or "")),
                squish(str(item.get("url") or item.get("@id") or "")))
    if isinstance(item, (list, tuple)):
        name = squish(str(item[0])) if item else ""
        url = squish(str(item[1])) if len(item) > 1 else ""
        return name, url
    return "", ""


def for_article(*, site_name: str, site_url: str, category: str = "", label_url: str = "",
                headline: str = "", url: str = "") -> list[tuple[str, str]]:
    """Home -> label/category -> article, the shape Blogger can actually serve."""
    items: list[tuple[str, str]] = [(squish(site_name) or "Home", squish(site_url))]
    if category:
        items.append((squish(category), label_url or squish(site_url).rstrip("/") +
                      f"/search/label/{category.replace(' ', '%20')}"))
    if headline and url:
        items.append((_clip(headline), squish(url)))
    return items


def validate(node: dict | None) -> list[str]:
    problems: list[str] = []
    if not node:
        return ["no breadcrumb node"]
    elements = node.get("itemListElement") or []
    if len(elements) < 2:
        problems.append("a breadcrumb trail needs at least two items")
    for index, element in enumerate(elements, start=1):
        if element.get("position") != index:
            problems.append(f"position {element.get('position')} should be {index}")
        if not element.get("name"):
            problems.append(f"item {index} has no name")
        item = element.get("item")
        if isinstance(item, dict) and not str(item.get("@id", "")).startswith("http"):
            problems.append(f"item {index} URL is not absolute")
    if elements and elements[-1].get("item"):
        problems.append("the last breadcrumb should not be a link")
    return problems


def to_html(items: list[tuple[str, str]], *, separator: str = "›") -> str:
    """A visible breadcrumb trail that matches the markup."""
    parts: list[str] = []
    rows = [(squish(name), squish(url)) for name, url in items or [] if squish(name)]
    for index, (name, url) in enumerate(rows):
        if index == len(rows) - 1 or not url:
            parts.append(f'<span aria-current="page">{_esc(name)}</span>')
        else:
            parts.append(f'<a href="{_esc(url)}">{_esc(name)}</a>')
    if not parts:
        return ""
    joined = f'<span class="bsd-crumb-sep" aria-hidden="true">{_esc(separator)}</span>'.join(parts)
    return f'<nav class="bsd-breadcrumbs" aria-label="Breadcrumb"><ol>{joined}</ol></nav>'


def _esc(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
