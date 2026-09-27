"""The SEO subsystem: planning, on-page optimisation, structured data and sitemaps.

Everything here is deterministic and offline. `plan()` is the single entry point the
pipeline uses; the individual modules are usable on their own for audits, sitemap
generation and robots.txt policy.
"""

from . import audit, density, headings, internal_links, meta, planner, robots, schema, sitemap, slug, title
from .audit import AuditReport, actions, run, summary
from .planner import image_alt, plan, sitemap_documents, sitemap_entry
from .schema import graph, jsonld, script_tag
from .slug import build as build_slug
from .title import build as build_title

__all__ = [
    "audit", "density", "headings", "internal_links", "meta", "planner", "robots",
    "schema", "sitemap", "slug", "title",
    "AuditReport", "actions", "run", "summary",
    "image_alt", "plan", "sitemap_documents", "sitemap_entry",
    "graph", "jsonld", "script_tag", "build_slug", "build_title",
]
