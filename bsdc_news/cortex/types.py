"""Data contracts shared by the cortex engine, the SEO layer and the publisher.

Nothing here performs I/O: these are plain records so the whole pipeline stays
cacheable, inspectable and unit-testable offline.
"""

from dataclasses import dataclass, field


@dataclass
class ArticleRequest:
    """Everything needed to write one article. No API keys, no network, no cost."""

    title: str
    text: str
    source: str = ""
    url: str = ""
    published: str = ""
    author: str = ""
    image_url: str = ""
    image_caption: str = ""
    image_credit: str = ""
    related: list[str] = field(default_factory=list)
    category: str = ""
    target_words: int = 650
    min_words: int = 400
    tone: str = "news"              # news | analysis | explainer | brief
    language: str = "en"
    site_name: str = "bsdc news"
    internal_links: list[dict] = field(default_factory=list)   # {"title", "url", "anchor"}
    extra: dict = field(default_factory=dict)

    @property
    def char_budget(self) -> int:
        """How much source text the writer is allowed to read."""
        return max(4000, self.target_words * 8)


@dataclass
class Fact:
    """One atomic claim lifted from the source text, with provenance."""

    text: str
    score: float = 0.0
    kind: str = "statement"         # statement | number | quote | definition | comparison
    entities: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()
    sentence_index: int = 0
    words: int = 0


@dataclass
class Section:
    """A planned block of the finished article."""

    heading: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    level: int = 2
    kind: str = "body"              # lede | body | context | faq | tldr | outlook


@dataclass
class ArticleDraft:
    """The finished, ready-to-render article."""

    headline: str
    body_html: str
    dek: str = ""
    meta_description: str = ""
    category: str = ""
    tags: tuple[str, ...] = ()
    sections: tuple[Section, ...] = ()
    facts: tuple[Fact, ...] = ()
    faq: tuple[tuple[str, str], ...] = ()
    tldr: tuple[str, ...] = ()
    keywords: dict = field(default_factory=dict)
    outline: list[str] = field(default_factory=list)
    words: int = 0
    quality_score: int = 0
    seo_score: int = 0
    readability: dict = field(default_factory=dict)
    sentiment: dict = field(default_factory=dict)
    entities: tuple[str, ...] = ()
    confidence: float = 0.0
    machine_written: bool = True
    engine: str = "cortex"
    timings: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


@dataclass
class SeoPlan:
    """Every SEO decision for one article, so the renderer can stay dumb."""

    title_tag: str = ""
    headline: str = ""
    slug: str = ""
    meta_description: str = ""
    canonical: str = ""
    primary_keyword: str = ""
    secondary_keywords: list[str] = field(default_factory=list)
    lsi_keywords: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    headings: list[tuple[int, str]] = field(default_factory=list)
    internal_links: list[dict] = field(default_factory=list)
    image_alts: list[str] = field(default_factory=list)
    faq: list[tuple[str, str]] = field(default_factory=list)
    breadcrumbs: list[tuple[str, str]] = field(default_factory=list)
    json_ld: list[dict] = field(default_factory=dict)
    open_graph: dict = field(default_factory=dict)
    twitter_card: dict = field(default_factory=dict)
    score: int = 0
    checks: list[tuple[str, bool, str]] = field(default_factory=list)   # (name, ok, detail)

    def failing_checks(self) -> list[str]:
        return [f"{name}: {detail}" for name, ok, detail in self.checks if not ok]
