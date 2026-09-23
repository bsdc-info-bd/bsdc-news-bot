"""Non-AI fallback writer ("news brief").

When every AI provider is unavailable the site keeps publishing: we build an
honest, clearly-attributed brief from the extracted article using extractive
summarisation (sentence scoring by keyword centrality + position).  Nothing is
invented; quoted sentences are attributed to the original outlet and readers
are sent to the original story.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .ai.base import ArticleDraft
from .dedupe import STOPWORDS, keywords
from .utils import esc, normalize_space, truncate, word_count

# Sentence boundary: terminal punctuation, optional closing quote/bracket, whitespace,
# then an uppercase letter/digit/opening quote.  Implemented without variable-width
# look-behind (unsupported by Python's re module).
_BOUNDARY_RE = re.compile(r"([.!?][\"'”’)]?)\s+(?=[A-Z0-9“\"'(])")
_ABBREVIATIONS = ("mr.", "mrs.", "ms.", "dr.", "prof.", "inc.", "ltd.", "co.", "corp.", "jr.", "sr.", "st.",
                  "vs.", "u.s.", "u.k.", "e.g.", "i.e.", "no.", "approx.", "est.", "gen.", "sen.", "rep.")
_BAD_SENT = re.compile(r"(click here|subscribe|newsletter|sign up|follow us|advertis|affiliate|"
                       r"we may earn|commission|cookie|all rights reserved|read more|getty images)", re.I)


def _split_paragraph(para: str) -> list[str]:
    pieces = _BOUNDARY_RE.split(para)
    # re.split with one capture group -> [text, punct, text, punct, ..., text]
    sentences: list[str] = []
    buf = ""
    for i in range(0, len(pieces), 2):
        chunk = pieces[i] + (pieces[i + 1] if i + 1 < len(pieces) else "")
        buf = f"{buf} {chunk}".strip() if buf else chunk.strip()
        if buf.lower().endswith(_ABBREVIATIONS) and i + 2 < len(pieces):
            continue  # "Dr. Smith" – keep joining
        sentences.append(buf)
        buf = ""
    if buf:
        sentences.append(buf)
    return sentences


def split_sentences(text: str) -> list[str]:
    sents: list[str] = []
    for para in normalize_space(text).split("\n"):
        for s in _split_paragraph(para.strip()):
            s = s.strip()
            if 8 <= word_count(s) <= 60 and not _BAD_SENT.search(s):
                sents.append(s)
    return sents


def rank_sentences(sentences: list[str], title: str = "") -> list[tuple[int, float]]:
    freq: Counter = Counter()
    for s in sentences:
        freq.update(w for w in keywords(s) if w not in STOPWORDS)
    if not freq:
        return [(i, 0.0) for i in range(len(sentences))]
    top = freq.most_common(1)[0][1]
    title_kw = keywords(title)
    scored = []
    n = len(sentences)
    for i, s in enumerate(sentences):
        kws = keywords(s)
        if not kws:
            scored.append((i, 0.0))
            continue
        centrality = sum(freq[w] / top for w in kws) / math.sqrt(len(kws))
        position = 1.0 - (i / max(1, n)) * 0.6
        title_bonus = 0.6 * len(kws & title_kw) / max(1, len(title_kw))
        numbers = 0.15 if re.search(r"\d", s) else 0.0
        quote = 0.1 if re.search(r"[\"“].+[\"”]", s) else 0.0
        scored.append((i, centrality * position + title_bonus + numbers + quote))
    return scored


def summarize(text: str, title: str = "", max_sentences: int = 6) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []
    ranked = sorted(rank_sentences(sentences, title), key=lambda x: x[1], reverse=True)
    chosen = sorted(i for i, _ in ranked[:max_sentences])
    return [sentences[i] for i in chosen]


def build_brief(title: str, text: str, source: str, source_url: str, description: str = "",
                category: str = "", tags: list[str] | None = None, related: list[str] | None = None) -> ArticleDraft:
    """Lead (2 sentences) + 3 key points + up to 2 detail sentences — every sentence used once,
    at most ~7 short attributed excerpts, always linking to the original report."""
    sentences = split_sentences(text)
    lead_sents = sentences[:2]
    rest = sentences[2:]
    ranked = sorted(rank_sentences(rest, title), key=lambda x: x[1], reverse=True)
    top = [i for i, _ in ranked[:5]]
    point_idx = sorted(top[:3])
    detail_idx = sorted(top[3:5])
    points = [truncate(rest[i], 180) for i in point_idx]
    body_sents = [rest[i] for i in detail_idx]

    parts: list[str] = []
    lead = " ".join(lead_sents) or description or title
    parts.append(f"<p><strong>{esc(source)} reports:</strong> {esc(lead)}</p>")
    if points:
        parts.append("<h2>Key Points</h2><ul>" + "".join(f"<li>{esc(p)}</li>" for p in points) + "</ul>")
    if body_sents:
        parts.append("<h2>The Details</h2>")
        for i in range(0, len(body_sents), 2):
            parts.append(f"<p>{esc(' '.join(body_sents[i:i + 2]))}</p>")
    if related:
        parts.append("<h2>Wider Coverage</h2>"
                     f"<p>The story is also being covered by {esc(', '.join(related[:4]))}, "
                     "indicating broad interest across the technology press.</p>")
    parts.append("<h2>Read the Full Story</h2>"
                 f"<p>This is a short news brief prepared by our desk. For the complete report, "
                 f"including all quotes and context, read the original article at "
                 f"<a href=\"{esc(source_url)}\" rel=\"nofollow noopener\" target=\"_blank\">{esc(source)}</a>.</p>")

    meta = truncate(description or lead or title, 158)
    return ArticleDraft(
        headline=title,
        body_html="\n".join(parts),
        meta_description=meta,
        focus_keyword=" ".join(list(keywords(title))[:3]),
        category=category,
        tags=list(tags or [])[:6],
        key_points=points,
        faq=[],
        provider="brief",
        model="extractive",
        ai_generated=False,
    )
