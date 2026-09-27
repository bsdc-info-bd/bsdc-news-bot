"""Heading structure: one H1, keyword-bearing H2s, no skipped levels.

Headings are the second thing a crawler reads after the title, so this module
derives an outline from the draft, checks it against the structural rules that
matter for accessibility and SEO, and can rewrite weak headings into specific ones.
"""

import re

from ..cortex.text.normalize import squish

MAX_H2 = 8
MIN_H2 = 2
HEADING_MAX_CHARS = 70
_GENERIC = {
    "introduction", "overview", "summary", "conclusion", "details", "more",
    "background", "about", "general", "other", "misc", "notes", "info",
    "information", "update", "updates", "news", "story", "article", "content",
    "read more", "see also", "related", "final thoughts", "wrapping up",
}
_QUESTION = re.compile(r"\b(what|why|how|when|where|which|who|is|are|does|can|should)\b",
                       re.IGNORECASE)


def collect(html: str) -> list[tuple[int, str]]:
    """Every heading in the document, in order, as (level, text)."""
    out: list[tuple[int, str]] = []
    for match in re.finditer(r"<h([1-6])[^>]*>(.*?)</h\1>", html or "", re.S | re.I):
        text = squish(re.sub(r"<[^>]+>", "", match.group(2)))
        if text:
            out.append((int(match.group(1)), text))
    return out


def outline(headings: list[tuple[int, str]]) -> list[tuple[int, str, int]]:
    """(level, text, depth) with depth showing the nesting for debugging."""
    out: list[tuple[int, str, int]] = []
    stack: list[int] = []
    for level, text in headings:
        while stack and stack[-1] >= level:
            stack.pop()
        out.append((level, text, len(stack)))
        stack.append(level)
    return out


def audit(headings: list[tuple[int, str]], *, keyword: str = "",
          title: str = "") -> list[tuple[str, bool, str]]:
    """Structural and relevance checks on the heading tree."""
    h1 = [text for level, text in headings if level == 1]
    h2 = [text for level, text in headings if level == 2]
    levels = [level for level, _ in headings]
    skipped = []
    previous = 1
    for level in levels:
        if level > previous + 1:
            skipped.append(f"H{previous}->H{level}")
        previous = level
    checks = [
        ("single_h1", len(h1) == 1, f"{len(h1)} H1 tag(s)"),
        ("h1_present", bool(h1), "an H1 is required"),
        ("h2_count", MIN_H2 <= len(h2) <= MAX_H2, f"{len(h2)} H2 sections"),
        ("no_skipped_levels", not skipped, ", ".join(skipped) or "levels are sequential"),
        ("heading_length", all(len(text) <= HEADING_MAX_CHARS for _, text in headings),
         f"longest is {max((len(text) for _, text in headings), default=0)} chars"),
        ("no_generic_headings", not [text for text in h2 if text.lower().strip(":?.") in _GENERIC],
         ", ".join(text for text in h2 if text.lower().strip(":?.") in _GENERIC) or "all specific"),
    ]
    if keyword:
        hits = sum(1 for text in h2 if keyword.lower() in text.lower())
        checks.append(("keyword_in_headings", hits >= 1 or not h2,
                       f"keyword appears in {hits} of {len(h2)} H2s"))
    if title and h1:
        checks.append(("h1_matches_title", squish(h1[0]).lower() == squish(title).lower(),
                       "H1 should equal the article headline"))
    return checks


def keyword_coverage(headings: list[tuple[int, str]], keywords: list[str]) -> dict[str, int]:
    """How many headings mention each keyword."""
    text = " ".join(item for _, item in headings).lower()
    return {keyword: text.count(keyword.lower()) for keyword in keywords if keyword}


def strengthen(heading: str, *, keyword: str = "", entity: str = "") -> str:
    """Turn a generic heading into a specific one using real article terms."""
    text = squish(heading)
    if text.lower().strip(":?.") not in _GENERIC:
        return text
    subject = entity or keyword
    if not subject:
        return text
    mapping = {
        "details": f"What {subject} confirmed",
        "overview": f"{subject} at a glance",
        "summary": f"{subject} in brief",
        "background": f"Why {subject} matters",
        "introduction": f"{subject} explained",
        "conclusion": f"What happens next for {subject}",
        "update": f"Latest on {subject}",
        "news": f"{subject}: what we know",
    }
    return mapping.get(text.lower().strip(":?."), f"{subject}: {text}")


def question_headings(headings: list[tuple[int, str]]) -> list[str]:
    """Headings phrased as questions — the ones that win featured snippets."""
    return [text for _, text in headings if _QUESTION.search(text) and text.endswith("?")]


def inject(html: str, headings: list[tuple[int, str]]) -> str:
    """Replace heading text in place, keeping the existing tags and attributes."""
    out = html or ""
    queue = list(headings)
    def replace(match: re.Match[str]) -> str:
        if not queue:
            return match.group(0)
        level, text = queue.pop(0)
        tag = match.group(1)
        attrs = match.group(2)
        return f"<h{tag}{attrs}>{text}</h{tag}>"
    return re.sub(r"<h([1-6])([^>]*)>.*?</h\1>", replace, out, flags=re.S | re.I)
