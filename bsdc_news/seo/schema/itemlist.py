"""ItemList markup for related-article and category listings."""

from ...cortex.text.normalize import squish


def build(items: list[dict] | list[str], *, name: str = "", number_of_items: int = 0) -> dict | None:
    """An ordered list of pages (related coverage, most-read, category index)."""
    rows: list[dict] = []
    for position, item in enumerate(items or [], start=1):
        url, title = _pair(item)
        if not url:
            continue
        node: dict = {"@type": "ListItem", "position": position, "url": squish(url)}
        if title:
            node["name"] = squish(title)[:110]
        rows.append(node)
    if not rows:
        return None
    node: dict = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": rows,
                  "numberOfItems": number_of_items or len(rows)}
    if name:
        node["name"] = squish(name)[:110]
    return node


def _pair(item) -> tuple[str, str]:
    if isinstance(item, dict):
        return (squish(str(item.get("url", ""))), squish(str(item.get("title", ""))))
    return squish(str(item)), ""


def related(posts: list[dict], *, name: str = "Related coverage") -> dict | None:
    return build(posts, name=name)


def validate(node: dict | None) -> list[str]:
    problems: list[str] = []
    if not node:
        return ["no ItemList node"]
    elements = node.get("itemListElement") or []
    if not elements:
        problems.append("ItemList is empty")
    for index, element in enumerate(elements, start=1):
        if element.get("position") != index:
            problems.append(f"position {element.get('position')} should be {index}")
        if not str(element.get("url", "")).startswith("http"):
            problems.append(f"item {index} url is not absolute")
    return problems
