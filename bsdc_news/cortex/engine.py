"""The cortex engine: analyse → plan → write → quality gate → revise.

This is the whole writing system, and it uses no external model, no API key and no
network call. Everything it produces is derived from the source article by the
bundled analysis and writing modules, then checked against measurable quality bars
and revised until it passes or the budget runs out.

The pipeline for one article:

1. normalise and language-check the source text
2. extract entities, numbers, quotes and ranked facts
3. plan keywords and the section outline (word budget per section)
4. check novelty against already-published titles and bodies
5. generate and score headline candidates, then build the lede
6. write each section from its assigned facts, paraphrasing verbatim sentences
7. assemble TL;DR, bullets, spec table, FAQ, sources and disclosure into HTML
8. score quality (length, readability, coherence, style, originality, SEO basics)
9. revise against the failing checks and re-score
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from ..errors import ContentRejected, DuplicateContent
from .analysis import clickbait, langid, readability, sentiment, summarizer
from .analysis import entities as entities_mod
from .analysis import facts as facts_mod
from .analysis import keywords as keywords_mod
from .analysis import numbers as numbers_mod
from .analysis import quotes as quotes_mod
from .lexicon import loader
from .semantic import coherence as coherence_mod
from .semantic import fingerprint
from .semantic import novelty as novelty_mod
from .text import normalize
from .text import sentences as sentences_mod
from .types import ArticleDraft, ArticleRequest, Fact
from .writing import attribution, compose, simplify
from .writing import bullets as bullets_mod
from .writing import faq as faq_mod
from .writing import headline as headline_mod
from .writing import lede as lede_mod
from .writing import outline as outline_mod
from .writing import sections as sections_mod
from .writing import style as style_mod
from .writing import tldr as tldr_mod


def _length_floor(req, analysis=None) -> int:
    """The shortest article the evidence can support.

    A 214-word source cannot produce an honest 450-word article: the extra words would
    be repetition dressed up as reporting. The floor therefore scales with the source,
    so short stories come out short (or fall back to a brief) instead of being padded.
    """
    source = (getattr(analysis, "text", "") or "") or (getattr(req, "text", "") or "")
    source_words = len(source.split())
    if not source_words:
        return int(getattr(req, "min_words", 0) or 0)
    return min(int(getattr(req, "min_words", 0) or 0), max(160, int(source_words * 1.2)))


ENGINE_NAME = "BSDC Cortex"
ENGINE_VERSION = "7.0"


@dataclass
class Analysis:
    """Everything the engine learned about one source article."""

    text: str = ""
    sentences: list[str] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    entities: list = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)
    actor: str = ""
    place: str = ""
    quotes: list = field(default_factory=list)
    numbers: list = field(default_factory=list)
    number_phrases: list[str] = field(default_factory=list)
    keyword_set: object = None
    intent: str = "news"
    language: str = "en"
    language_confidence: float = 0.0
    sentiment: dict = field(default_factory=dict)
    readability: dict = field(default_factory=dict)
    headline_slots: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def primary_keyword(self) -> str:
        return getattr(self.keyword_set, "primary", "") if self.keyword_set else ""

    def as_dict(self) -> dict:
        return {
            "sentences": len(self.sentences), "facts": len(self.facts),
            "entities": self.entity_names[:12], "actor": self.actor,
            "quotes": len(self.quotes), "numbers": self.number_phrases[:8],
            "intent": self.intent, "language": self.language,
            "sentiment": self.sentiment, "readability": self.readability,
            "notes": self.notes,
        }


@dataclass
class QualityReport:
    """Measured quality of a finished draft, with the action for each failure."""

    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    score: int = 0
    words: int = 0
    grade: float = 0.0
    coherence: float = 0.0
    originality: float = 0.0
    actions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(passed for _, passed, _ in self.checks)

    def failing(self) -> list[str]:
        return [f"{name}: {detail}" for name, passed, detail in self.checks if not passed]

    def as_dict(self) -> dict:
        return {"score": self.score, "words": self.words, "grade": round(self.grade, 2),
                "coherence": round(self.coherence, 1), "originality": round(self.originality, 3),
                "checks": [{"name": name, "ok": passed, "detail": detail}
                           for name, passed, detail in self.checks],
                "failing": self.failing(), "actions": self.actions}


class CortexEngine:
    """Deterministic article writer. Same input always produces the same output."""

    def __init__(self, *, grade_target: float = 0.0, rewrite: bool = True,
                 min_facts: int = 3, min_confidence: float = 0.30,
                 max_quality_passes: int = 2, novelty_threshold: float = 0.42,
                 supported_languages: tuple[str, ...] = ("en",),
                 gazetteer: entities_mod.Gazetteer | None = None,
                 engine_name: str = ENGINE_NAME, version: str = ENGINE_VERSION) -> None:
        self.grade_target = grade_target
        self.rewrite = rewrite
        self.min_facts = min_facts
        self.min_confidence = min_confidence
        self.max_quality_passes = max(1, max_quality_passes)
        self.novelty_threshold = novelty_threshold
        self.supported_languages = supported_languages
        self.engine_name = engine_name
        self.version = version
        self._gazetteer = gazetteer or default_gazetteer()

    # ------------------------------------------------------------------ analysis

    def gazetteer(self) -> entities_mod.Gazetteer:
        return self._gazetteer

    def analyze(self, req: ArticleRequest) -> Analysis:
        """Run every read-only analysis pass over the source text."""
        started = time.perf_counter()
        text = normalize.normalize(req.text or "")
        if not text.strip():
            raise ContentRejected("source text is empty; nothing to write about")
        text = text[: req.char_budget]

        language, confidence = langid.detect(text)
        if not langid.is_supported(text, supported=self.supported_languages):
            raise ContentRejected(f"source language {language!r} is not supported "
                                  f"({', '.join(self.supported_languages)})")

        sentences = [item for item in sentences_mod.split_sentences(text)
                     if not summarizer.is_noise(item)] or sentences_mod.split_sentences(text)
        found = entities_mod.extract(text, gazetteer=self._gazetteer)
        entity_names = entities_mod.names(found)
        facts = facts_mod.extract(text, limit=30, entity_names=entity_names[:10])
        facts = facts_mod.dedupe_facts(facts)
        quotes = quotes_mod.best(text, limit=3)
        extracted_numbers = numbers_mod.extract(text)
        number_phrases = list(dict.fromkeys(item.phrase() for item in extracted_numbers))
        keyword_set = keywords_mod.plan(text, headline=req.title, entity_names=entity_names[:8],
                                        numeric_phrases=number_phrases[:6])
        readable = compose.plain_text(text)
        feeling = sentiment.analyze(readable, per_sentence=False)
        reading = readability.analyze(readable)

        actor = _actor(found, text)
        place = _place(found)
        analysis = Analysis(
            text=text, sentences=sentences, facts=facts, entities=found,
            entity_names=entity_names, actor=actor, place=place, quotes=quotes,
            numbers=extracted_numbers, number_phrases=number_phrases,
            keyword_set=keyword_set, intent=keyword_set.intent, language=language,
            language_confidence=round(confidence, 3),
            sentiment={"score": round(feeling.score, 3), "label": feeling.label,
                       "intensity": round(feeling.intensity, 3)},
            readability={"grade": round(reading.get("average_grade", 0.0), 2),
                         "flesch": round(reading.get("flesch_reading_ease", 0.0), 1),
                         "score": reading.get("score", 0),
                         "words": reading.get("counts", {}).get("words", 0)},
            headline_slots=_headline_slots(req.title, actor, entity_names, number_phrases),
        )
        if len(facts) < self.min_facts:
            analysis.notes.append(f"only {len(facts)} facts extracted")
        if not quotes:
            analysis.notes.append("no attributable quotes found")
        analysis.notes.append(f"analysed in {(time.perf_counter() - started) * 1000:.0f}ms")
        return analysis

    # -------------------------------------------------------------------- writing

    def write(self, req: ArticleRequest, *, analysis: Analysis | None = None,
              published_titles: list[str] | None = None,
              published_bodies: list[str] | None = None) -> ArticleDraft:
        """Write one complete article. Raises ContentRejected/DuplicateContent on failure."""
        timings: dict[str, float] = {}
        overall = time.perf_counter()
        analysis = analysis or self.analyze(req)
        timings["analyze"] = round(time.perf_counter() - overall, 3)

        step = time.perf_counter()
        report = novelty_mod.score(req.title, analysis.text,
                                   published_titles=published_titles or [],
                                   published_bodies=published_bodies or [],
                                   threshold=self.novelty_threshold)
        if not report.novel:
            raise DuplicateContent(f"story already covered (novelty {report.score:.2f}): "
                                   + "; ".join(report.reasons[:2]),
                                   reasons=report.reasons, score=report.score)
        timings["novelty"] = round(time.perf_counter() - step, 3)

        step = time.perf_counter()
        primary = analysis.primary_keyword()
        # Padding an article to a word target the source cannot support would mean
        # inventing filler, so the target is capped at what the evidence allows.
        source_words = len(analysis.text.split())
        floor_words = _length_floor(req, analysis)
        target_words = min(req.target_words, max(floor_words, int(source_words * 1.45)))
        plan = outline_mod.plan(facts=analysis.facts, quotes=analysis.quotes,
                                numbers=analysis.number_phrases,
                                target_words=target_words, tone=req.tone,
                                primary_keyword=primary, intent=analysis.intent,
                                actor=analysis.actor, related_count=len(req.related))
        plan = outline_mod.reorder(plan)
        budgets = outline_mod.word_budgets(plan, target_words)
        timings["outline"] = round(time.perf_counter() - step, 3)

        step = time.perf_counter()
        headline, candidates = headline_mod.best(
            req.title, primary_keyword=primary, secondary=getattr(analysis.keyword_set, "secondary", []),
            entities=analysis.entity_names[:6], numbers=analysis.number_phrases[:6],
            published=published_titles or [], **analysis.headline_slots)
        timings["headline"] = round(time.perf_counter() - step, 3)

        step = time.perf_counter()
        lede = lede_mod.build(analysis.facts, headline=headline, entities=analysis.entity_names[:6],
                              actor=analysis.actor)
        if not lede:
            raise ContentRejected("could not build a lede from the source facts")
        lede, _ = style_mod.apply(lede)
        if self.grade_target:
            lede = simplify.simplify(lede, target_grade=self.grade_target)[0]
        dek = lede_mod.summary_dek(analysis.facts, lede=lede)
        timings["lede"] = round(time.perf_counter() - step, 3)

        step = time.perf_counter()
        used = {normalize.squish(fact.text) for fact in analysis.facts[:1]}
        key_numbers = bullets_mod.key_numbers(analysis.facts)
        spec_rows = bullets_mod.specs_from_numbers(analysis.numbers, source=analysis.text)
        glance = bullets_mod.at_a_glance(analysis.facts)
        written: list[sections_mod.WrittenSection] = []
        for section in plan.sections:
            if section.kind == "lede":
                continue
            section.word_budget = budgets.get(section.kind, section.word_budget)
            produced = sections_mod.write(section, source=analysis.text, facts=analysis.facts,
                                          used=used, bullets=key_numbers if section.kind == "details" else None,
                                          specs=spec_rows if section.kind == "specs" else None,
                                          quotes=analysis.quotes, rewrite=self.rewrite,
                                          grade_target=self.grade_target)
            if produced.paragraphs or produced.bullets or produced.specs or produced.quotes:
                written.append(produced)
        timings["sections"] = round(time.perf_counter() - step, 3)

        step = time.perf_counter()
        tldr_items = tldr_mod.build(analysis.facts, lede=lede)
        faq_items = faq_mod.build(analysis.text, subject=primary or analysis.actor,
                                  facts=analysis.facts, limit=5)
        if req.tone == "news" and faq_items:
            faq_items = faq_items[:3]
        publishers = [attribution.publisher_name(req.url, req.source)] if (req.url or req.source) else []
        source_block = attribution.source_block(urls=[req.url] if req.url else [],
                                                publishers=publishers)
        credibility = attribution.credibility_note(publishers=publishers,
                                                   quote_count=len(analysis.quotes),
                                                   source_count=1 if req.url else 0)
        disclosure = attribution.disclosure(engine=self.engine_name, version=self.version)
        timings["blocks"] = round(time.perf_counter() - step, 3)

        step = time.perf_counter()
        body = compose.compose(
            lede=lede, sections=written, tldr=compose.tldr_block(analysis.facts, lede=lede),
            faq=faq_items, source_block=source_block, disclosure=disclosure,
            credibility=credibility)
        draft = ArticleDraft(
            headline=headline, body_html=body, dek=dek,
            meta_description=meta_description(lede, dek, primary,
                                              extra=tldr_items[0] if tldr_items else ""),
            category=req.category, tags=tags_for(analysis, primary),
            sections=tuple(compose.to_sections(written, lede=lede)),
            facts=tuple(analysis.facts[:12]), faq=tuple(faq_items), tldr=tuple(tldr_items),
            keywords=getattr(analysis.keyword_set, "as_dict", lambda: {})(),
            outline=[section.kind for section in plan.sections],
            words=compose.word_count(body), entities=tuple(analysis.entity_names[:10]),
            machine_written=True, engine=f"{self.engine_name} {self.version}".strip(),
            stats={"bullets": glance, "specs": [list(row) for row in spec_rows],
                   "headline_candidates": [item.as_dict() for item in candidates[:8]],
                   "outline_notes": plan.notes, "analysis": analysis.as_dict(),
                   "target_words": target_words, "source_words": source_words,
                   "novelty": report.as_dict(), "language": analysis.language,
                   "sentiment": analysis.sentiment},
        )
        timings["compose"] = round(time.perf_counter() - step, 3)

        step = time.perf_counter()
        quality = self.quality(draft, req, analysis, target_words=target_words)
        passes = 0
        while not quality.ok and passes < self.max_quality_passes:
            passes += 1
            draft = self.revise(draft, req, analysis, quality, target_words=target_words)
            quality = self.quality(draft, req, analysis, target_words=target_words)
        draft.quality_score = quality.score
        draft.readability = {"grade": round(quality.grade, 2), "words": quality.words,
                             "coherence": round(quality.coherence, 1),
                             "originality": round(quality.originality, 3)}
        draft.sentiment = analysis.sentiment
        draft.confidence = round(confidence_of(analysis, quality), 3)
        threshold = self.min_confidence
        if str(getattr(analysis, "language", "en") or "en") != "en":
            # The grounding heuristics (gazetteer, stopword lists, quote patterns) are
            # English-tuned, so a Bangla draft scores lower on evidence it really has.
            threshold = round(threshold * 0.6, 3)
        if draft.confidence < threshold:
            raise ContentRejected(
                f"draft confidence {draft.confidence:.2f} is below {threshold:.2f}; "
                "the source did not support a publishable article")
        timings["quality"] = round(time.perf_counter() - step, 3)
        timings["total"] = round(time.perf_counter() - overall, 3)
        draft.timings = timings
        draft.stats["quality"] = quality.as_dict()
        draft.stats["passes"] = passes
        return draft

    # -------------------------------------------------------------------- quality

    @staticmethod
    def length_floor(req: ArticleRequest, analysis: Analysis | None = None) -> int:
        """Public helper: the shortest article this source can honestly support."""
        return _length_floor(req, analysis)

    def quality(self, draft: ArticleDraft, req: ArticleRequest, analysis: Analysis,
                *, target_words: int = 0) -> QualityReport:
        """Measure a draft against the publication bars."""
        target_words = target_words or req.target_words
        text = compose.prose_text(draft.body_html)
        word_total = len(text.split())
        reading = readability.analyze(text)
        grade = float(reading.get("average_grade", 0.0))
        flow = coherence_mod.analyze(text)
        overlap = fingerprint.overlap_ratio(analysis.text, text)
        report = QualityReport(words=word_total, grade=grade, coherence=flow.score,
                               originality=round(1.0 - overlap, 4))
        checks = report.checks

        floor = _length_floor(req, analysis)
        checks.append(("length", floor <= word_total <= int(target_words * 1.4),
                       f"{word_total} words (target {target_words}, floor {floor})"))
        checks.append(("readability", grade <= 14.5,
                       f"grade {grade:.1f}"))
        checks.append(("coherence", flow.score >= 32.0,
                       f"coherence {flow.score:.1f}/100"))
        checks.append(("originality", overlap <= 0.62,
                       f"{overlap:.0%} of the wording is copied from the source"))
        style_report = style_mod.check(text, known_caps=source_caps(analysis.text))
        checks.append(("style", not style_report.issues,
                       "; ".join(str(issue) for issue in style_report.issues[:3]) or "clean"))
        bait, reasons = clickbait.score_headline(draft.headline)
        checks.append(("headline_clickbait", not bait, "; ".join(reasons[:2]) or "clean"))
        checks.append(("headline_length", 30 <= len(draft.headline) <= headline_mod.HARD_MAX,
                       f"{len(draft.headline)} chars"))
        checks.append(("meta_description", 110 <= len(draft.meta_description) <= 165,
                       f"{len(draft.meta_description)} chars"))
        primary = analysis.primary_keyword()
        if primary:
            haystack = f"{draft.headline} {draft.meta_description} {text[:1200]}".lower()
            checks.append(("keyword_coverage", primary.lower() in haystack,
                           f"primary keyword {primary!r}"))
        checks.append(("structure", len(draft.sections) >= 2 and bool(draft.tldr),
                       f"{len(draft.sections)} sections, {len(draft.tldr)} key points"))
        checks.append(("sourcing", bool(draft.stats.get("analysis", {}).get("notes") is not None)
                       and ("bsd-sources" in draft.body_html or "bsd-disclosure" in draft.body_html),
                       "source and disclosure blocks present"))
        banned = loader.banned_phrases()
        hits = [phrase for phrase in banned if phrase.lower() in text.lower()]
        checks.append(("banned_phrases", not hits, ", ".join(hits[:3]) or "none"))
        checks.append(("confidence_facts", len(analysis.facts) >= self.min_facts,
                       f"{len(analysis.facts)} facts"))

        passed = sum(1 for _, ok, _ in checks if ok)
        report.score = int(round(passed / max(1, len(checks)) * 100))
        report.actions = _actions_for(checks, word_total, req, grade, overlap,
                                      target_words=target_words)
        return report

    # -------------------------------------------------------------------- revise

    def revise(self, draft: ArticleDraft, req: ArticleRequest, analysis: Analysis,
               report: QualityReport, *, target_words: int = 0) -> ArticleDraft:
        """Apply the specific fixes the quality report asked for."""
        failing = {name for name, ok, _ in report.checks if not ok}
        text_sections = list(draft.sections)

        if "style" in failing or "readability" in failing:
            text_sections = [_rewrite_section(section, self.grade_target or 11.0)
                             for section in text_sections]
        if "originality" in failing:
            text_sections = [_paraphrase_section(section, analysis.sentences) for section in text_sections]
        if "length" in failing:
            text_sections = _fix_length(text_sections, analysis, report.words, req,
                                        target_words=target_words or req.target_words)
        if "coherence" in failing:
            text_sections = _smooth(text_sections)

        body = _rebuild_body(draft, text_sections)
        draft.sections = tuple(text_sections)
        draft.body_html = body
        draft.words = compose.word_count(body)
        if "meta_description" in failing:
            lede_text = text_sections[0].paragraphs[0] if text_sections and text_sections[0].paragraphs else draft.dek
            draft.meta_description = meta_description(lede_text, draft.dek, analysis.primary_keyword())
        if "headline_length" in failing:
            trimmed = headline_mod.shorten(draft.headline, limit=headline_mod.IDEAL_MAX)
            if trimmed:
                draft.headline = trimmed[0]
        return draft


# ---------------------------------------------------------------------- helpers


def source_caps(text: str) -> set[str]:
    """Acronyms the source itself writes in capitals; they are not style errors."""
    import re

    return {token for token in re.findall(r"\b[A-Z]{2,}\b", text or "")}


def default_gazetteer() -> entities_mod.Gazetteer:
    """Gazetteer built from the bundled data file plus the place list."""
    entries: dict[str, tuple[str, tuple[str, ...]]] = {}
    for name, entry in loader.gazetteer_entries().items():
        entries[name] = (str(entry.get("kind", "MISC")), tuple(entry.get("aliases", [])))
    for place in loader.place_names():
        entries.setdefault(place, ("PLACE", ()))
    return entities_mod.Gazetteer(entries)


def _actor(found: list, text: str) -> str:
    """The organisation or person the story is about."""
    for entity in entities_mod.by_kind(found, "ORG")[:1]:
        return entity.text
    for entity in entities_mod.by_kind(found, "PERSON")[:1]:
        return entity.text
    for entity in found[:1]:
        return entity.text
    return ""


def _place(found: list) -> str:
    for entity in entities_mod.by_kind(found, "PLACE")[:1]:
        return entity.text
    return ""


def _headline_slots(title: str, actor: str, entity_names: list[str],
                    number_phrases: list[str]) -> dict:
    """Slots for headline templates, taken from the source title only.

    Keeping every slot inside one sentence is what stops the writer from asserting
    a price, place or date that the source never put together.
    """
    import re

    cleaned = headline_mod.clean(title or "")
    verb = ""
    match = re.search(r"\b([A-Z][a-z]+(?:es|s|ed|ing)?)\b", cleaned)
    if match:
        verb = match.group(1)
    detail = ""
    numbers_in_title = [phrase for phrase in number_phrases if phrase in cleaned.lower()]
    if numbers_in_title:
        index = cleaned.lower().find(numbers_in_title[0])
        detail = cleaned[max(0, index - 28):index + len(numbers_in_title[0]) + 12].strip(" ,")
    elif "," in cleaned:
        detail = cleaned.split(",", 1)[1].strip()
    subject = next((name for name in entity_names if name.lower() in cleaned.lower()), "")
    # Only keys best() accepts. "numbers" stays out because best() receives the
    # numeric phrases separately, and a duplicate argument would let them disagree.
    return {"actor": actor if actor.lower() in cleaned.lower() else "",
            "verb": verb, "detail": detail[:60], "subject": subject or ""}


def meta_description(lede: str, dek: str, primary_keyword: str = "", *,
                     extra: str = "", minimum: int = 120, maximum: int = 160) -> str:
    """A SERP description built from real text, trimmed to the pixel budget.

    Several candidates are tried in order and the first that fits *without losing a
    figure* wins: a description that reads "ships in the second half" because the
    year was trimmed away is worse than a shorter, complete one.
    """
    candidates = [normalize.squish(lede), normalize.squish(dek), normalize.squish(extra)]
    if lede and dek and normalize.squish(dek) != normalize.squish(lede):
        candidates.append(f"{normalize.squish(lede).rstrip('.')}. {normalize.squish(dek)}")
    for candidate in candidates:
        if not candidate:
            continue
        fitted = _fit_description(candidate.rstrip("."), minimum=minimum, maximum=maximum)
        if fitted:
            return _clamp(_finish_description(fitted, primary_keyword, maximum), maximum)
    best_effort = next((item for item in candidates if item), "")
    return _clamp(_finish_description(best_effort[:maximum].rstrip(" ,;:-"), primary_keyword, maximum),
                  maximum)


def _clamp(text: str, maximum: int) -> str:
    """Never hand a search engine a description longer than the budget.

    `_finish_description` can add the focus keyword, which used to push a 154-character
    description to 161 and get it truncated with an ellipsis in the SERP.
    """
    if len(text) <= maximum:
        return text
    cut = text[:maximum]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-.").rstrip() + "." if cut else text[:maximum]


def _fit_description(text: str, *, minimum: int, maximum: int) -> str:
    """Trim at clause boundaries; refuse if that would drop a number."""
    if minimum <= len(text) <= maximum:
        return text
    if len(text) < minimum:
        return ""
    boundaries = [match.end() for match in re.finditer(r"[,;] |\.\s", text)]
    usable = [position for position in boundaries if position <= maximum - 1]
    for position in reversed(usable):
        piece = text[:position].rstrip(" ,;:-")
        if _digits(piece) == _digits(text[:maximum]):
            return piece if len(piece) >= minimum - 25 else ""
    words = text.split()
    while words and len(" ".join(words)) > maximum:
        words.pop()
    while words and words[-1].lower().strip(".,;:") in _DANGLING_TAIL:
        words.pop()
    piece = " ".join(words).rstrip(" ,;:-")
    if _digits(piece) != _digits(text[: len(piece) + 12]):
        return ""
    return piece if len(piece) >= minimum - 25 else ""


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _finish_description(text: str, primary_keyword: str, maximum: int) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if (primary_keyword and len(primary_keyword.split()) > 1
            and primary_keyword.lower() not in text.lower()):
        # Only a real keyphrase earns the prefix; a bare word would read as spam.
        text = f"{primary_keyword.title()}: {text}"[:maximum].rstrip(" ,;:-")
    return f"{text}." if not text.endswith((".", "!", "?")) else text


_DANGLING_TAIL = frozenset(["in", "of", "to", "at", "for", "on", "by", "with", "from",
                            "and", "or", "the", "a", "an", "its", "their", "as", "that"])


def tags_for(analysis: Analysis, primary_keyword: str = "", *, limit: int = 8) -> tuple[str, ...]:
    """Blogger labels: the primary keyword plus the strongest entities."""
    out: list[str] = []
    if primary_keyword:
        out.append(primary_keyword)
    for entity in analysis.entity_names:
        if entity.lower() not in {item.lower() for item in out}:
            out.append(entity)
        if len(out) >= limit:
            break
    for term in getattr(analysis.keyword_set, "secondary", [])[:3]:
        if term.lower() not in {item.lower() for item in out}:
            out.append(term)
        if len(out) >= limit:
            break
    return tuple(out[:limit])


def confidence_of(analysis: Analysis, report: QualityReport) -> float:
    """How much the source supports this article, 0..1."""
    value = 0.0
    value += min(0.30, len(analysis.facts) * 0.03)
    value += min(0.15, len(analysis.entity_names) * 0.03)
    value += 0.10 if analysis.quotes else 0.0
    value += min(0.10, len(analysis.number_phrases) * 0.02)
    value += 0.10 * (report.score / 100.0)
    value += 0.10 if analysis.language_confidence > 0.7 else 0.04
    value += 0.05 if report.originality > 0.45 else 0.0
    return min(1.0, value)


def _actions_for(checks: list, words: int, req: ArticleRequest, grade: float,
                 overlap: float, *, target_words: int = 0) -> list[str]:
    target_words = target_words or req.target_words
    actions: list[str] = []
    for name, ok, _ in checks:
        if ok:
            continue
        if name == "length":
            actions.append("expand" if words < req.min_words else "trim")
        elif name == "readability":
            actions.append(f"simplify to grade {min(12.0, grade - 2):.0f}")
        elif name == "originality":
            actions.append("paraphrase the closest paragraphs")
        elif name == "coherence":
            actions.append("add transitions and merge stub paragraphs")
        elif name == "style":
            actions.append("apply house style")
        elif name == "meta_description":
            actions.append("rebuild meta description")
        elif name == "headline_length":
            actions.append("shorten headline")
        else:
            actions.append(f"fix {name}")
    return list(dict.fromkeys(actions))


def _rewrite_section(section, grade_target: float):
    section.paragraphs = [style_mod.apply(simplify.simplify(item, target_grade=grade_target)[0])[0]
                          for item in section.paragraphs]
    section.bullets = [style_mod.apply(item)[0] for item in section.bullets]
    return section


def _paraphrase_section(section, source_sentences: list[str]):
    if not source_sentences:
        return section
    section.paragraphs = [paraphrase_against(item, source_sentences) for item in section.paragraphs]
    return section


def paraphrase_against(paragraph: str, source_sentences: list[str]) -> str:
    from .writing import paraphrase as paraphrase_mod

    if not any(fingerprint.shingle_overlap(paragraph, item) > 0.35 for item in source_sentences):
        return paragraph
    return paraphrase_mod.unique_against(paragraph, source_sentences)[0] or paragraph


def _fix_length(sections: list, analysis: Analysis, words: int, req: ArticleRequest,
                *, target_words: int = 0) -> list:
    """Add facts when short, drop the weakest paragraphs when long."""
    target_words = target_words or req.target_words
    if words < max(req.min_words, int(target_words * 0.8)) and analysis.facts:
        used = {normalize.squish(paragraph) for section in sections for paragraph in section.paragraphs}
        extra = [fact for fact in analysis.facts if normalize.squish(fact.text) not in used]
        if extra:
            from .types import Section

            needed = max(4, (max(req.min_words, int(target_words * 0.9)) - words) // 22)
            produced = sections_mod.paragraph([fact.text for fact in extra[:needed]], budget=90)
            existing = {section.heading.lower() for section in sections}
            heading = outline_mod.heading_for("context", analysis.primary_keyword(),
                                              analysis.actor)
            if heading.lower() in existing:
                heading = outline_mod.heading_for("background")
            if produced and heading.lower() not in existing:
                sections.append(Section(heading=heading, paragraphs=produced, kind="context"))
        return sections
    if words > int(target_words * 1.4):
        overflow = words - int(target_words * 1.25)
        for section in reversed(sections):
            while section.paragraphs and overflow > 0 and len(section.paragraphs) > 1:
                dropped = section.paragraphs.pop()
                overflow -= len(dropped.split())
            if overflow <= 0:
                break
    return sections


def _smooth(sections: list) -> list:
    """Merge stub paragraphs and re-join with connectors for better flow."""
    from .writing import transitions

    for section in sections:
        section.paragraphs = sections_mod.reorder_paragrahs(section.paragraphs)
        if len(section.paragraphs) > 1:
            joined = [section.paragraphs[0]]
            for following in section.paragraphs[1:]:
                relation = transitions.transition_needed(joined[-1], following)
                joined.append(transitions.join(joined[-1], following)
                              if relation != "sequence" else following)
            section.paragraphs = joined
    return sections


def _rebuild_body(draft: ArticleDraft, sections: list) -> str:
    """Rebuild the HTML from the (possibly revised) section records."""
    from .writing.sections import WrittenSection

    lede = ""
    written: list[WrittenSection] = []
    for section in sections:
        if section.kind == "lede":
            lede = section.paragraphs[0] if section.paragraphs else ""
            continue
        written.append(WrittenSection(kind=section.kind, heading=section.heading,
                                      paragraphs=list(section.paragraphs),
                                      bullets=list(section.bullets)))
    keep = draft.body_html
    faq_items = list(draft.faq)
    source_block = _extract_block(keep, "bsd-sources")
    disclosure = _extract_block(keep, "bsd-disclosure")
    credibility = _extract_block(keep, "bsd-credibility")
    tldr_block = _extract_block(keep, "bsd-tldr")
    return compose.compose(lede=lede, sections=written, tldr=tldr_block, faq=faq_items,
                           source_block=source_block, disclosure=disclosure,
                           credibility=credibility)


def _extract_block(html_body: str, class_name: str) -> str:
    """Pull a previously rendered block out of the body so it survives a revision."""
    import re

    match = re.search(rf'(<div class="{class_name}".*?</div>|<p class="{class_name}".*?</p>)',
                      html_body or "", re.S)
    return match.group(1) if match else ""
