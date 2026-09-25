"""Section writing: turn planned sections into grounded, readable prose.

Each section pulls the facts assigned to it by the outline, groups them into
paragraphs of two to three sentences, joins them with rotating discourse
connectors, paraphrases sentences that are verbatim copies of the source, and
enforces house style. Quote sections keep the original wording inside blockquotes.
"""

from dataclasses import dataclass, field

from ..semantic.similarity import token_similarity
from ..text.normalize import squish
from ..text.sentences import split_sentences
from ..types import Fact
from . import paraphrase, simplify, transitions
from .outline import SectionPlan
from .style import apply as apply_style

PARAGRAPH_MIN = 2
PARAGRAPH_MAX = 3
VERBATIM_THRESHOLD = 0.86


@dataclass
class WrittenSection:
    kind: str
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    specs: list[tuple[str, str]] = field(default_factory=list)
    quotes: list[tuple[str, str]] = field(default_factory=list)
    fact_indexes: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def text(self) -> str:
        return " ".join(self.paragraphs)

    def word_count(self) -> int:
        return len(self.text().split()) + sum(len(bullet.split()) for bullet in self.bullets)


def select_sentences(source: str, *, facts: list[Fact], indexes: list[int],
                     used: set[str], limit: int = 6) -> list[str]:
    """Sentences assigned to this section, minus any already used elsewhere."""
    sentences = split_sentences(source or "")
    picked: list[str] = []
    for index in indexes:
        if not 0 <= index < len(facts):
            continue
        text = squish(facts[index].text)
        if text in used:
            continue
        match = next((item for item in sentences if token_similarity(item, text) > 0.72), "")
        picked.append(match or text)
        used.add(text)
    for item in picked:
        used.add(item)
    return picked[:limit]


def paragraph(sentences: list[str], *, budget: int = 70, rewrite: bool = True,
              source_sentences: list[str] | None = None) -> list[str]:
    """Group sentences into paragraphs of PARAGRAPH_MIN..PARAGRAPH_MAX sentences."""
    source_sentences = source_sentences or []
    cleaned: list[str] = []
    for sentence in sentences:
        text = squish(sentence)
        if not text or len(text.split()) < 3:
            continue
        text, _ = apply_style(text)
        if rewrite and source_sentences and _is_verbatim(text, source_sentences):
            # unique_against returns (text, attempt log); the log is dropped here
            # because the engine records originality separately.
            text = paraphrase.unique_against(text, source_sentences)[0] or text
        cleaned.append(text)
    out: list[str] = []
    chunk: list[str] = []
    words = 0
    for text in cleaned:
        chunk.append(text)
        words += len(text.split())
        if len(chunk) >= PARAGRAPH_MAX or words >= budget:
            out.append(_join(chunk))
            chunk, words = [], 0
    if len(chunk) == 1 and out:
        out[-1] = f"{out[-1]} {chunk[0]}"
    elif chunk:
        if len(chunk) < PARAGRAPH_MIN and out:
            out[-1] = f"{out[-1]} {chunk[0]}"
        else:
            out.append(_join(chunk))
    return [item for item in out if item]


def _join(sentences: list[str]) -> str:
    """Join sentences with rotating connectors where the relation warrants one."""
    if not sentences:
        return ""
    out = sentences[0]
    for following in sentences[1:]:
        relation = transitions.transition_needed(out, following)
        out = f"{out} {transitions.join(out, following)}" if relation != "sequence" else f"{out} {following}"
    return squish(out)


def _is_verbatim(sentence: str, source_sentences: list[str]) -> bool:
    return any(token_similarity(sentence, item) >= VERBATIM_THRESHOLD for item in source_sentences)


def write(section: SectionPlan, *, source: str, facts: list[Fact], used: set[str],
          bullets: list[str] | None = None, specs: list[tuple[str, str]] | None = None,
          quotes: list | None = None, rewrite: bool = True, grade_target: float = 0.0) -> WrittenSection:
    """Produce the prose for one planned section."""
    written = WrittenSection(kind=section.kind, heading=section.heading,
                             fact_indexes=list(section.fact_indexes))
    source_sentences = split_sentences(source or "")
    if section.kind == "quotes":
        limit = 2
        for quote in (quotes or [])[:limit]:
            text = squish(getattr(quote, "text", "") or "")
            speaker = squish(getattr(quote, "speaker", "") or "")
            if len(text.split()) < 4:
                continue
            written.quotes.append((text, speaker))
        if not written.quotes:
            written.notes.append("no quotable sentence met the length bar")
        return written
    if section.kind == "specs":
        written.specs = list(specs or [])[:6]
        written.bullets = list(bullets or [])[:4]
        if not written.specs and not written.bullets:
            written.notes.append("no numeric facts for a spec block")
        return written
    sentences = select_sentences(source, facts=facts, indexes=section.fact_indexes, used=used)
    if not sentences:
        fallback = [squish(fact.text) for fact in facts if squish(fact.text) not in used][:3]
        sentences = [item for item in fallback if item]
        used.update(sentences)
    if not sentences:
        written.notes.append("no unused facts available")
        return written
    paragraphs = paragraph(sentences, budget=max(35, section.word_budget), rewrite=rewrite,
                           source_sentences=source_sentences)
    if grade_target:
        paragraphs = [simplify.simplify(item, target_grade=grade_target)[0] for item in paragraphs]
    written.paragraphs = split_long(paragraphs)
    if section.kind in {"details", "impact"} and bullets:
        written.bullets = [item for item in bullets if item not in " ".join(paragraphs)][:4]
    return written


MAX_PARAGRAPH_WORDS = 80


def split_long(paragraphs: list[str], *, limit: int = MAX_PARAGRAPH_WORDS) -> list[str]:
    """Split any paragraph longer than `limit` words at a sentence boundary.

    Walls of text are the most common mobile readability failure and they lose the
    on-page audit, so nothing leaves the writer longer than the limit.
    """
    out: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph.split()) <= limit:
            out.append(paragraph)
            continue
        chunk: list[str] = []
        for piece in split_sentences(paragraph):
            chunk.append(piece)
            if len(" ".join(chunk).split()) >= limit * 0.55:
                out.append(squish(" ".join(chunk)))
                chunk = []
        if chunk:
            if out and len(" ".join(chunk).split()) < 12:
                out[-1] = squish(f"{out[-1]} {' '.join(chunk)}")
            else:
                out.append(squish(" ".join(chunk)))
    return [item for item in out if item]


def reorder_paragrahs(paragraphs: list[str]) -> list[str]:
    """Shortest-first is wrong for news: keep the assigned order but merge stubs."""
    out: list[str] = []
    for item in paragraphs:
        if out and len(item.split()) < 8:
            out[-1] = f"{out[-1]} {item}"
            continue
        out.append(item)
    return out
