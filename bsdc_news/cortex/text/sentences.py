"""Sentence segmentation that survives real news HTML.

A naive ``split('.')`` destroys decimals ("3.5-inch"), abbreviations ("U.S."),
initials ("T. Cook") and quoted speech. Instead every candidate boundary is
matched against a punctuation + capitalisation pattern after the tricky spans
have been hidden behind placeholders.
"""

import re

from .abbrev import protect_abbreviations
from .normalize import normalize

_URL = re.compile(r"https?://\S+|www\.\S+")
_DECIMAL = re.compile(r"\b\d+\.\d+\b|\b\d{1,3}(?:,\d{3})+\.\d+")
_ELLIPSIS = re.compile(r"\.{2,}|…")
_VERSION = re.compile(r"\bv\d+\.\d+(?:\.\d+)*\b|\biOS \d+\.\d+|\bAndroid \d+\.\d+")
# Python look-behind must be fixed width, so "up to two closing quote characters
# after the terminal mark" is spelled out as three alternatives instead of {0,2}.
# \x00 marks a hidden abbreviation, which may legitimately start a sentence ("T. Cook").
_LOOKAHEAD = r"""[ \t]+(?=["'(\[]{0,2}[A-Z0-9$\x00])"""
_TAILS = (r'[.!?…]', r'[.!?…]["\)\]]', r'[.!?…]["\)\]]{2}')
_BOUNDARY = re.compile("|".join(f"(?<={tail}){_LOOKAHEAD}" for tail in _TAILS))
_LONG_WORD_SPLIT = re.compile(r"(?:,\s+|\s+(?:and|but|which|while|because|although|after|before|so)\s+)")


def split_sentences(text: str, *, min_chars: int = 12, max_chars: int = 700) -> list[str]:
    """Return the sentences of ``text`` in order: trimmed, merged and de-duplicated."""
    text = normalize(text)
    if not text:
        return []
    protected: list[str] = []

    def hide(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    guarded = _URL.sub(hide, text)
    guarded = _VERSION.sub(hide, guarded)
    guarded = _DECIMAL.sub(hide, guarded)
    guarded = protect_abbreviations(guarded, hide)
    guarded = _ELLIPSIS.sub(hide, guarded)

    raw: list[str] = []
    for paragraph in guarded.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        start = 0
        for match in _BOUNDARY.finditer(paragraph):
            raw.append(paragraph[start:match.start()])
            start = match.end()
        raw.append(paragraph[start:])

    sentences: list[str] = []
    for piece in raw:
        piece = re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], piece)
        piece = re.sub(r"\s+", " ", piece).strip(" \t-*\u2022")
        if not piece:
            continue
        if len(piece) > max_chars:
            sentences.extend(split_long(piece, max_chars))
        elif len(piece) < min_chars:
            if sentences and len(sentences[-1]) < 240:
                sentences[-1] = f"{sentences[-1]} {piece}".strip()
            else:
                sentences.append(piece)
        else:
            sentences.append(piece)

    seen: set[str] = set()
    out: list[str] = []
    for sentence in sentences:
        key = re.sub(r"[^a-z0-9 ]", "", sentence.casefold())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(sentence)
    return out


def split_long(sentence: str, max_chars: int = 700) -> list[str]:
    """Break an over-long sentence at commas and conjunctions."""
    parts = _LONG_WORD_SPLIT.split(sentence)
    parts = [part for part in parts if part and part.strip()]
    if len(parts) < 2:
        return [sentence]
    chunks: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}, {part}".strip(", ") if current else part
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks or [sentence]


def word_count(sentence: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’\-$]+", sentence))


def first_sentence(text: str) -> str:
    sentences = split_sentences(text, min_chars=4)
    return sentences[0] if sentences else ""
