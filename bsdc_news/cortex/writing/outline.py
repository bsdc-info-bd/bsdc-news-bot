"""Article planning: decide the structure before writing a single sentence.

The planner is what makes the output read like journalism rather than a summary:
it enforces the inverted pyramid, budgets words per section from the available
evidence, and refuses to plan a section it has no facts for.
"""

from dataclasses import dataclass, field

from ..analysis.facts import timeline
from ..lexicon import loader

SECTION_ORDER = ("lede", "details", "specs", "context", "quotes", "impact", "outlook", "faq")


@dataclass
class SectionPlan:
    kind: str
    heading: str
    word_budget: int
    fact_indexes: list[int] = field(default_factory=list)
    required: bool = False
    reason: str = ""


@dataclass
class Outline:
    sections: list[SectionPlan] = field(default_factory=list)
    tone: str = "news"
    total_words: int = 0
    intent: str = "news"
    primary_keyword: str = ""
    notes: list[str] = field(default_factory=list)

    def kinds(self) -> list[str]:
        return [section.kind for section in self.sections]

    def budget(self, kind: str) -> int:
        return next((section.word_budget for section in self.sections if section.kind == kind), 0)


_SMALL_WORDS = {"a", "an", "the", "and", "or", "but", "for", "of", "on", "in", "at", "to",
                "with", "by", "from", "as", "is", "are", "was", "were", "be", "vs"}


def _title_case(phrase: str) -> str:
    """Title case that does not produce "Bangladesh'S" or "Iphone"."""
    words = phrase.split()
    out: list[str] = []
    for index, word in enumerate(words):
        if word.isupper() and len(word) <= 5:
            out.append(word)                     # keep acronyms: BTRC, HBM4, NVLink
        elif index and word.lower() in _SMALL_WORDS:
            out.append(word.lower())
        elif "'" in word:
            head, _, tail = word.partition("'")
            out.append(f"{head[:1].upper()}{head[1:].lower()}'{tail.lower()}")
        else:
            out.append(word[:1].upper() + word[1:].lower() if word.islower() else word)
    return " ".join(out)


def heading_for(kind: str, primary_keyword: str = "", actor: str = "", detail: str = "") -> str:
    """A specific, keyword-aware H2 — generic headings waste an SEO slot."""
    subject = _title_case(primary_keyword) if primary_keyword else "the announcement"
    table = {
        "details": f"What {actor or subject} confirmed",
        "specs": f"{subject} specifications and numbers",
        "context": f"Why {subject} matters now",
        "quotes": "What they said",
        "impact": f"What it means for {detail or 'users'}",
        "outlook": "What happens next",
        "faq": f"{subject}: questions answered",
        "comparison": f"{subject} compared",
        "background": f"{subject} in context",
    }
    return table.get(kind, subject)


def plan(*, facts: list, quotes: list, numbers: list, target_words: int = 650,
         tone: str = "news", primary_keyword: str = "", intent: str = "news",
         actor: str = "", audience: str = "", related_count: int = 0) -> Outline:
    """Build the section plan from the evidence actually available."""
    notes: list[str] = []
    sections: list[SectionPlan] = []
    fact_count = len(facts)
    numeric = [fact for fact in facts if fact.kind == "number"]
    definition = [fact for fact in facts if fact.kind == "definition"]
    dated = timeline(facts)

    lede_words = max(45, min(85, int(target_words * 0.11)))
    sections.append(SectionPlan(kind="lede", heading="", word_budget=lede_words,
                                fact_indexes=[0] if facts else [], required=True,
                                reason="inverted pyramid: the newest fact first"))
    used = {0} if facts else set()

    remaining = max(0, target_words - lede_words)
    detail_indexes = [i for i in range(1, min(fact_count, 6)) if i not in used]
    if detail_indexes:
        budget = int(remaining * 0.30)
        sections.append(SectionPlan(kind="details",
                                    heading=heading_for("details", primary_keyword, actor),
                                    word_budget=budget, fact_indexes=detail_indexes[:3],
                                    required=True, reason="core facts after the lede"))
        used.update(detail_indexes[:3])

    if numbers and (numeric or len(numbers) >= 2):
        sections.append(SectionPlan(kind="specs",
                                    heading=heading_for("specs", primary_keyword, actor),
                                    word_budget=int(remaining * 0.16),
                                    fact_indexes=[fact.sentence_index for fact in numeric][:4],
                                    reason=f"{len(numbers)} numeric facts available"))

    context_indexes = [i for i in range(fact_count) if i not in used]
    if context_indexes and (definition or fact_count > 6 or related_count):
        sections.append(SectionPlan(kind="context",
                                    heading=heading_for("context", primary_keyword, actor),
                                    word_budget=int(remaining * 0.20),
                                    fact_indexes=context_indexes[:3],
                                    reason="background keeps readers on page"))
        used.update(context_indexes[:3])
    elif not context_indexes:
        notes.append("no spare facts for a context section")

    quote_limit = int(loader.style_rules().get("quote_limit_per_article", 2))
    if quotes and quote_limit > 0:
        sections.append(SectionPlan(kind="quotes", heading=heading_for("quotes"),
                                    word_budget=int(remaining * 0.12),
                                    fact_indexes=[], reason=f"{len(quotes)} usable quote(s)"))
    else:
        notes.append("no attributable quotes in the source")

    if intent in {"informational", "news"} and fact_count > 4:
        sections.append(SectionPlan(kind="impact",
                                    heading=heading_for("impact", primary_keyword, actor,
                                                        audience or "users"),
                                    word_budget=int(remaining * 0.14),
                                    fact_indexes=[i for i in range(fact_count) if i not in used][:2],
                                    reason="reader impact section"))

    if dated:
        sections.append(SectionPlan(kind="outlook", heading=heading_for("outlook"),
                                    word_budget=int(remaining * 0.10), fact_indexes=[],
                                    reason=f"{len(dated)} dated statement(s)"))
    if tone == "explainer" or intent == "informational":
        sections.append(SectionPlan(kind="faq", heading=heading_for("faq", primary_keyword),
                                    word_budget=int(remaining * 0.12), fact_indexes=[],
                                    reason="FAQ block for long-tail queries"))

    if tone == "brief":
        sections = [section for section in sections if section.kind in {"lede", "details", "specs"}]

    total = sum(section.word_budget for section in sections)
    return Outline(sections=sections, tone=tone, total_words=total, intent=intent,
                   primary_keyword=primary_keyword, notes=notes)


def word_budgets(outline: Outline, target_words: int) -> dict[str, int]:
    """Normalise section budgets so they add up to the target exactly."""
    raw = {section.kind: max(20, section.word_budget) for section in outline.sections}
    total = sum(raw.values()) or 1
    scaled = {kind: max(20, int(value / total * target_words)) for kind, value in raw.items()}
    drift = target_words - sum(scaled.values())
    if scaled and drift:
        largest = max(scaled, key=lambda kind: scaled[kind])
        scaled[largest] += drift
    return scaled


def reorder(outline: Outline) -> Outline:
    """Canonical reading order, keeping only planned sections."""
    order = {kind: index for index, kind in enumerate(SECTION_ORDER)}
    outline.sections.sort(key=lambda section: order.get(section.kind, 99))
    return outline
