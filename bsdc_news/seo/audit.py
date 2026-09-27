"""The on-page audit: 40 checks grouped into weighted categories.

Each check returns (name, passed, detail) so the result is explainable — a score
with no reason behind it cannot be acted on by a revision pass. Categories are
weighted because a missing title matters more than a slightly long paragraph.
"""

import re
from dataclasses import dataclass, field

from ..cortex.analysis import readability as readability_mod
from ..cortex.text.normalize import squish
from ..cortex.writing import compose as compose_mod
from . import density, internal_links
from . import headings as headings_mod
from . import meta as meta_mod
from . import slug as slug_mod
from . import title as title_mod

WEIGHTS = {
    "title": 1.4, "meta": 1.2, "url": 1.0, "headings": 1.1, "content": 1.0,
    "keywords": 1.3, "links": 0.9, "media": 0.8, "structured": 1.2, "trust": 1.0,
    "technical": 0.9,
}
Check = tuple[str, bool, str]


@dataclass
class AuditReport:
    checks: list[Check] = field(default_factory=list)
    score: int = 0
    by_category: dict[str, list[Check]] = field(default_factory=dict)
    weighted: float = 0.0
    blocking: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocking and self.score >= 70

    def failing(self) -> list[str]:
        return [f"{name}: {detail}" for name, passed, detail in self.checks if not passed]

    def as_dict(self) -> dict:
        return {"score": self.score, "weighted": round(self.weighted, 2),
                "blocking": self.blocking,
                "checks": [{"name": name, "ok": passed, "detail": detail}
                           for name, passed, detail in self.checks],
                "by_category": {key: [{"name": n, "ok": o, "detail": d} for n, o, d in value]
                                for key, value in self.by_category.items()}}


_BARE_AMPERSAND = re.compile(r"&(?!#\d+;|#x[0-9a-fA-F]+;|[a-zA-Z][a-zA-Z0-9]{1,31};)")
BLOCKING_CHECKS = {"title_present", "meta_present", "single_h1", "canonical_absolute",
                   "language_declared", "word_count_floor"}


def run(*, title_tag: str, headline: str, description: str, slug: str, canonical: str,
        html: str, keywords: list[str], primary_keyword: str = "", images: list[dict] | None = None,
        links: list[dict] | None = None, jsonld_nodes: dict | None = None,
        language: str = "en", author: str = "", published: str = "", sources: int = 0,
        disclosure: bool = False, site_name: str = "", related_count: int = 0,
        word_floor: int = 350) -> AuditReport:
    """Every on-page check for one article."""
    images = images or []
    links = links if links is not None else internal_links.outgoing_links(html)
    report = AuditReport()
    prose = compose_mod.prose_text(html)
    words_total = len(prose.split())
    # Blogger renders the post title as the page H1, so the audit sees the markup the
    # crawler will see rather than the body fragment alone.
    audited_html = html if "<h1" in (html or "").lower() else f"<h1>{squish(headline)}</h1>{html}"
    heading_list = headings_mod.collect(audited_html)
    heading_text = [text for _, text in heading_list]

    def add(category: str, name: str, passed: bool, detail: str) -> None:
        report.checks.append((name, bool(passed), detail))
        report.by_category.setdefault(category, []).append((name, bool(passed), detail))
        if name in BLOCKING_CHECKS and not passed:
            report.blocking.append(name)

    # ---------------------------------------------------------------- title
    add("title", "title_present", bool(squish(title_tag)), squish(title_tag)[:60] or "empty")
    add("title", "title_length", title_mod.MIN_LENGTH <= len(title_tag) <= title_mod.HARD_MAX,
        f"{len(title_tag)} chars (ideal {title_mod.MIN_LENGTH}-{title_mod.IDEAL_MAX})")
    add("title", "title_differs_from_h1", title_mod.differs_from_h1(title_tag, headline),
        "title tag and H1 are not identical")
    stuffing = title_mod.stuffing_score(title_tag, keywords)
    add("title", "title_not_stuffed", stuffing <= 0.25, f"stuffing score {stuffing:.2f}")

    # ---------------------------------------------------------------- meta
    add("meta", "meta_present", bool(squish(description)), squish(description)[:60] or "empty")
    add("meta", "meta_length", meta_mod.MIN_LENGTH <= len(description) <= meta_mod.MAX_LENGTH,
        f"{len(description)} chars")
    add("meta", "meta_unique", squish(description).lower() != squish(headline).lower(),
        "description is not a copy of the headline")
    add("meta", "meta_ends_sentence", description.endswith((".", "!", "?")) or not description,
        "description ends with terminal punctuation")

    # ---------------------------------------------------------------- url
    add("url", "slug_present", bool(slug), slug or "empty")
    for name, passed, detail in slug_mod.audit(slug):
        add("url", name, passed, detail)
    add("url", "canonical_absolute", canonical.startswith("http"), canonical[:60] or "empty")
    add("url", "canonical_no_query", "?" not in canonical, "query strings split ranking signals")
    if primary_keyword:
        add("url", "keyword_in_slug", any(part in slug.lower()
                                          for part in primary_keyword.lower().split()),
            f"slug {slug!r}")

    # ---------------------------------------------------------------- headings
    for name, passed, detail in headings_mod.audit(heading_list, keyword=primary_keyword,
                                                   title=headline):
        add("headings", name, passed, detail)

    # ---------------------------------------------------------------- content
    add("content", "word_count_floor", words_total >= word_floor,
        f"{words_total} words (floor {word_floor})")
    add("content", "word_count_ceiling", words_total <= 2600, f"{words_total} words")
    metrics = readability_mod.analyze(prose)
    grade = float(metrics.get("average_grade", 0.0))
    add("content", "readability_grade", grade <= 14.0, f"grade {grade:.1f}")
    add("content", "readability_score", int(metrics.get("score", 0)) >= 40,
        f"readability {metrics.get('score', 0)}/100")
    paragraphs = [squish(re.sub(r"<[^>]+>", " ", block))
                  for block in re.findall(r"(?s)<p\b[^>]*>(.*?)</p>", html or "")]
    paragraphs = [item for item in paragraphs if item]
    long_paragraphs = sum(1 for item in paragraphs if len(item.split()) > 90)
    add("content", "paragraph_length", not long_paragraphs,
        f"{long_paragraphs} paragraph(s) over 90 words")
    add("content", "has_lists", "<ul" in html or "<ol" in html or "<table" in html,
        "a list or table breaks up the page")
    add("content", "no_lorem", not re.search(r"lorem ipsum|todo:|tbd|placeholder text",
                                             prose, re.I), "no placeholder copy")

    # ---------------------------------------------------------------- keywords
    if primary_keyword:
        metric = density.counts(prose, primary_keyword)
        first = squish(prose).split(". ")[0] if squish(prose) else ""
        value, _notes = density.score(
            density=float(metric["density"]),
            prominence_value=density.prominence(metric),
            in_title=primary_keyword.lower() in title_tag.lower(),
            in_first_sentence=primary_keyword.lower() in first.lower(),
            in_headings=sum(1 for text in heading_text if primary_keyword.lower() in text.lower()),
            in_meta=primary_keyword.lower() in description.lower(),
            in_url=any(part in slug.lower() for part in primary_keyword.lower().split()),
        )
        add("keywords", "keyword_placement", value >= 55, f"placement score {value}/100")
        add("keywords", "keyword_density",
            density.IDEAL_MIN <= float(metric["density"]) <= 3.2,
            f"density {metric['density']:.2f}% ({metric['hits']} hits)")
        add("keywords", "keyword_in_title", primary_keyword.lower() in title_tag.lower()
            or any(part in title_tag.lower() for part in primary_keyword.lower().split()),
            f"primary keyword {primary_keyword!r}")
        add("keywords", "keyword_prominence", density.prominence(metric) >= 0.35,
            f"prominence {density.prominence(metric):.2f}")
        flagged = density.stuffing_risk(prose, keywords)
        add("keywords", "no_stuffing", not flagged, "; ".join(flagged[:2]) or "clean")
        coverage = density.ngram_coverage(prose, keywords[:6])
        covered = sum(1 for value_ in coverage.values() if value_ > 0)
        add("keywords", "keyword_coverage", covered >= max(1, len(coverage) // 2),
            f"{covered}/{len(coverage)} planned keywords appear")
    add("keywords", "language_declared", bool(language), language or "unset")

    # ---------------------------------------------------------------- links
    if not links:
        links = internal_links.outgoing_links(audited_html)
    internal = [item for item in links if not item.get("external")]
    external = [item for item in links if item.get("external")]
    add("links", "has_internal_links", bool(internal) or related_count > 0,
        f"{len(internal)} internal link(s)")
    add("links", "has_external_source", bool(external) or sources > 0,
        f"{len(external)} external link(s)")
    add("links", "external_rel", all(item.get("nofollow") or "source" in item["url"]
                                     for item in external) if external else True,
        "outbound links carry rel attributes")
    empty_anchors = [item for item in links if not squish(item.get("anchor", ""))]
    add("links", "anchor_text_present", not empty_anchors,
        f"{len(empty_anchors)} empty anchor(s)")
    generic_anchors = [item for item in links
                       if re.match(r"^(read more|click here|here|link|more)$",
                                   squish(item.get("anchor", "")).lower())]
    add("links", "anchor_text_descriptive", not generic_anchors,
        f"{len(generic_anchors)} generic anchor(s)")
    add("links", "anchor_variety", internal_links.rotation([item.get("anchor", "") for item in links])
        >= 0.6, "anchor text is varied")
    add("links", "link_count_sane", len(links) <= 60, f"{len(links)} links on the page")

    # ---------------------------------------------------------------- media
    if images:
        missing_alt = [item for item in images if not squish(str(item.get("alt", "")))]
        add("media", "image_alt_text", not missing_alt,
            f"{len(missing_alt)} of {len(images)} image(s) missing alt")
        short_alt = [item for item in images if len(squish(str(item.get("alt", ""))).split()) < 3]
        add("media", "image_alt_descriptive", not short_alt,
            f"{len(short_alt)} alt text(s) under three words")
        add("media", "image_https", all(str(item.get("url", "")).startswith("https://")
                                        for item in images), "mixed content blocks indexing")
    else:
        add("media", "has_image", False, "no image: news rich results need one")

    # ---------------------------------------------------------------- structured data
    for name, node in (jsonld_nodes or {}).items():
        problems = _validate_node(name, node)
        add("structured", f"schema_{name}_valid", not problems,
            "; ".join(problems[:2]) or f"{name} markup valid")
    add("structured", "has_article_schema", bool((jsonld_nodes or {}).get("article")),
        "Article/NewsArticle markup present")

    # ---------------------------------------------------------------- trust / E-E-A-T
    add("trust", "author_named", bool(squish(author)) or site_name != "", author or site_name)
    add("trust", "sources_cited", sources > 0 or bool(external),
        f"{sources} source(s) cited")
    add("trust", "disclosure_present", disclosure, "machine-written disclosure shown")
    add("trust", "published_dated", bool(published), published or "no publication date")
    add("trust", "no_banned_claims", not re.search(
        r"\b(guaranteed|100% (?:accurate|true)|miracle|shocking truth)\b", prose, re.I),
        "no unverifiable claims")

    # ---------------------------------------------------------------- technical
    add("technical", "single_h1_markup", audited_html.count("<h1") <= 1,
        f"{audited_html.count('<h1')} h1 tag(s)")
    add("technical", "no_inline_scripts", "<script" not in re.sub(
        r'(?s)<script type="application/ld\+json">.*?</script>', "", html),
        "no blocking scripts in the body")
    bare_ampersands = len(_BARE_AMPERSAND.findall(html or ""))
    add("technical", "escaped_markup", bare_ampersands == 0,
        f"{bare_ampersands} bare ampersand(s)" if bare_ampersands else "entities escaped")
    add("technical", "no_duplicate_ids", _duplicate_ids(html) == 0,
        f"{_duplicate_ids(html)} duplicate id attribute(s)")
    add("technical", "closed_tags", _unclosed_tags(html) == 0,
        f"{_unclosed_tags(html)} unclosed block tag(s)")

    passed = sum(1 for _, ok, _ in report.checks if ok)
    weighted_total = 0.0
    weighted_passed = 0.0
    for category, items in report.by_category.items():
        weight = WEIGHTS.get(category, 1.0)
        for _, ok, _ in items:
            weighted_total += weight
            weighted_passed += weight if ok else 0.0
    report.weighted = round(weighted_passed / weighted_total * 100, 2) if weighted_total else 0.0
    report.score = int(round(passed / max(1, len(report.checks)) * 100))
    return report


def _validate_node(name: str, node) -> list[str]:
    from .schema import article, breadcrumb, faq, itemlist, organization

    validators = {"article": article.validate, "faq": faq.validate,
                  "breadcrumb": breadcrumb.validate, "itemlist": itemlist.validate,
                  "organization": organization.validate, "website": organization.validate}
    validator = validators.get(name)
    return validator(node) if validator else []


def _duplicate_ids(html: str) -> int:
    ids = re.findall(r'\sid="([^"]+)"', html or "")
    return len(ids) - len(set(ids))


def _unclosed_tags(html: str) -> int:
    problems = 0
    for tag in ("div", "p", "ul", "ol", "table", "blockquote", "section", "nav"):
        opened = len(re.findall(rf"<{tag}\b", html or "", re.I))
        closed = len(re.findall(rf"</{tag}>", html or "", re.I))
        if opened != closed:
            problems += abs(opened - closed)
    return problems


def summary(report: AuditReport) -> str:
    """A one-paragraph human-readable summary of the audit."""
    failing = report.failing()
    head = f"SEO score {report.score}/100 (weighted {report.weighted:.0f})."
    if not failing:
        return f"{head} All {len(report.checks)} checks passed."
    return f"{head} {len(failing)} check(s) need attention: " + "; ".join(failing[:6]) + "."


def actions(report: AuditReport) -> list[str]:
    """Ordered fix list, most damaging first."""
    order = ["title", "meta", "url", "headings", "keywords", "structured", "content",
             "trust", "links", "media", "technical"]
    out: list[str] = []
    for category in order:
        for name, ok, detail in report.by_category.get(category, []):
            if not ok:
                out.append(f"{category}/{name}: {detail}")
    return out
