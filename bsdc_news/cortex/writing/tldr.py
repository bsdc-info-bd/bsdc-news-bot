"""TL;DR block: three or four bullets a reader can scan in five seconds.

Distinct from the lede by construction — the lede is prose, the TL;DR is a list of
the highest-scoring facts, each clipped and de-duplicated against the others.
"""

from ..semantic.similarity import token_similarity
from ..text.normalize import squish
from ..types import Fact
from .bullets import _clip

MAX_ITEMS = 4
MAX_WORDS = 22


def build(facts: list[Fact], *, lede: str = "", limit: int = MAX_ITEMS) -> list[str]:
    """The top facts as scan-able bullets, never repeating the lede."""
    out: list[str] = []
    for fact in facts:
        if fact.kind == "quote":
            continue
        text = _clip(squish(fact.text))
        words = text.split()
        if len(words) < 4 or len(words) > MAX_WORDS + 6:
            if len(words) > MAX_WORDS + 6:
                text = _clip(" ".join(words[:MAX_WORDS]))
            else:
                continue
        if lede and token_similarity(text, lede) > 0.85:
            continue
        if any(token_similarity(text, existing) > 0.62 for existing in out):
            continue
        out.append(text)
        if len(out) >= limit:
            break
    return out


def as_text(facts: list[Fact], *, lede: str = "") -> str:
    """Plain-text version for notifications and social cards."""
    items = build(facts, lede=lede)
    if not items:
        return ""
    return " | ".join(item.rstrip(".") for item in items)


def as_markdown(facts: list[Fact], *, lede: str = "") -> str:
    items = build(facts, lede=lede)
    return "\n".join(f"- {item}" for item in items)
