"""The structured-data graph for one page.

Everything the page can say about itself in schema.org lives here: the article, the
publisher, the FAQ, the breadcrumbs, the images and the related list, assembled into
a single `@graph` so Google reads one coherent entity instead of competing nodes.
"""

from . import article, breadcrumb, faq, itemlist, organization

__all__ = ["article", "breadcrumb", "faq", "itemlist", "organization", "graph",
           "validate_all", "jsonld"]


def graph(*nodes: dict | None) -> dict:
    """Combine valid nodes into one @graph document."""
    items = [node for node in nodes if node]
    if not items:
        return {}
    for node in items:
        node.pop("@context", None)
    if len(items) == 1:
        return {"@context": "https://schema.org", **items[0]}
    return {"@context": "https://schema.org", "@graph": items}


def validate_all(nodes: dict[str, dict | None]) -> dict[str, list[str]]:
    """Run every builder's own validator and return the problems by node name."""
    problems: dict[str, list[str]] = {}
    validators = {"article": article.validate, "faq": faq.validate,
                  "breadcrumb": breadcrumb.validate, "itemlist": itemlist.validate,
                  "organization": organization.validate, "website": organization.validate}
    for name, node in nodes.items():
        validator = validators.get(name)
        if not validator:
            continue
        found = validator(node)
        if found:
            problems[name] = found
    return problems


def jsonld(document: dict | None, *, indent: int | None = None) -> str:
    """Serialise a schema document into a script tag body."""
    import json

    if not document:
        return ""
    return json.dumps(document, ensure_ascii=False, indent=indent, sort_keys=False)


def script_tag(document: dict | None) -> str:
    """The <script type="application/ld+json"> element for the page head."""
    body = jsonld(document)
    if not body:
        return ""
    return f'<script type="application/ld+json">{body}</script>'
