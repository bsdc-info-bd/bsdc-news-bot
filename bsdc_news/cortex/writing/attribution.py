"""Attribution, sourcing and the machine-written disclosure.

Every claim in the article must be traceable to a named source. This module builds
the source block, in-body attribution phrases, and the disclosure that states the
article was assembled automatically from published reporting — required for reader
trust and for Google's helpful-content expectations.
"""

import re
from datetime import UTC, datetime
from urllib.parse import urlparse

from ..lexicon import loader
from ..text.normalize import squish

_SAYS = re.compile(r"\b(said|says|told|stated|noted|added|explained|wrote|confirmed)\b", re.IGNORECASE)
_PUBLISHER_STRIP = re.compile(r"\s*[-|–]\s*(www\.)?[a-z0-9\-]+\.(com|org|net|io|co|news|dev|blog)$",
                              re.IGNORECASE)


def publisher_name(url: str = "", feed_title: str = "") -> str:
    """Human-readable publisher from a URL or feed title."""
    if feed_title:
        title = _PUBLISHER_STRIP.sub("", squish(feed_title)).strip()
        if title:
            return title
    if not url:
        return ""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    parts = host.split(".")
    name = parts[0] if parts else host
    return name.replace("-", " ").replace("_", " ").title()


def source_block(*, urls: list[str] | None = None, publishers: list[str] | None = None,
                 accessed: datetime | None = None, limit: int = 6) -> str:
    """HTML source list for the end of the article."""
    urls = [url for url in (urls or []) if url]
    publishers = publishers or []
    accessed = accessed or datetime.now(UTC)
    lines: list[str] = []
    seen: set[str] = set()
    for index, url in enumerate(urls[:limit]):
        if url in seen:
            continue
        seen.add(url)
        name = publishers[index] if index < len(publishers) and publishers[index] else publisher_name(url)
        host = urlparse(url).netloc.lower().removeprefix("www.")
        lines.append(f'<li><a href="{url}" rel="noopener noreferrer nofollow" target="_blank">{name or host}</a>'
                     f'{" &mdash; " + host if name and host and name.lower() != host else ""}</li>')
    if not lines:
        return ""
    stamp = accessed.strftime("%d %B %Y, %H:%M UTC")
    return ('<div class="bsd-sources"><h3>Sources</h3><ul>' + "".join(lines) +
            f'</ul><p class="bsd-accessed">Accessed {stamp}.</p></div>')


def disclosure(*, engine: str = "BSDC Cortex", version: str = "", reviewed: bool = False) -> str:
    """The machine-written disclosure shown under every article."""
    text = squish(loader.disclosure()) or (
        "This article was compiled automatically from published sources and checked "
        "by an automated quality pipeline.")
    if engine:
        text = text.replace("{engine}", engine)
    if version:
        text = text.replace("{version}", version)
    text = text.replace("{reviewed}", "editorially reviewed" if reviewed else "machine-checked")
    text = text.replace("{year}", str(datetime.now(UTC).year))
    return f'<p class="bsd-disclosure">{squish(text)}</p>'


def inline_attribution(claim: str, *, speaker: str = "", publisher: str = "") -> str:
    """Add an attribution tail to a claim that lacks one."""
    if not claim:
        return claim
    if _SAYS.search(claim) or not (speaker or publisher):
        return claim
    who = speaker or publisher
    return squish(f"{claim.rstrip('.')} , according to {who}.")


def speakers(quotes: list, limit: int = 4) -> list[str]:
    """Distinct speakers found in extracted quotes."""
    out: list[str] = []
    for quote in quotes:
        speaker = getattr(quote, "speaker", "") or ""
        if speaker and speaker not in out:
            out.append(speaker)
        if len(out) >= limit:
            break
    return out


def credibility_note(*, publishers: list[str], quote_count: int = 0,
                     source_count: int = 0) -> str:
    """A short, factual line about how the story was verified (never inflated)."""
    parts: list[str] = []
    if source_count > 1:
        parts.append(f"compiled from {source_count} published reports")
    elif source_count == 1:
        parts.append("compiled from a single published report")
    if publishers:
        parts.append(f"sourced to {publishers[0]}")
    if quote_count:
        parts.append(f"{quote_count} direct quotation{'s' if quote_count > 1 else ''} retained verbatim")
    if not parts:
        return ""
    if len(parts) == 1:
        joined = parts[0]
    else:
        joined = f"{', '.join(parts[:-1])} and {parts[-1]}"
    return f'<p class="bsd-credibility">This article was {joined}.</p>'
