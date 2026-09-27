"""Unicode and whitespace normalisation — stage one of every text path."""

import re
import unicodedata

SMART_QUOTES = {
    "\u2018": "'", "\u2019": "'", "\u201b": "'", "\u2039": "'", "\u203a": "'",
    "\u201c": '"', "\u201d": '"', "\u201f": '"', "\u00ab": '"', "\u00bb": '"',
    "\u2013": "-", "\u2014": " - ", "\u2015": " - ", "\u2212": "-", "\u2043": "-",
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u2009": " ", "\u200a": " ",
    "\u2026": "...", "\u00bd": "1/2", "\u00bc": "1/4", "\u00be": "3/4",
    "\u2022": "*", "\u00b7": "*", "\u25cf": "*", "\u25aa": "*", "\u2023": "*",
    "\ufeff": "", "\u200b": "", "\u200c": "", "\u200d": "", "\u2060": "",
}

_ZERO_WIDTH = re.compile("[\u200b-\u200f\u2060\ufeff]")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_MULTI_NL = re.compile(r"\n{3,}")
_HTML_ENTITY = re.compile(r"&(amp|lt|gt|quot|apos|nbsp|#\d{1,5}|#x[0-9a-fA-F]{1,5});")
_SIMPLE_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " "}


def fold_quotes(text: str) -> str:
    """Replace typographic punctuation with plain ASCII equivalents."""
    for src, dst in SMART_QUOTES.items():
        if src in text:
            text = text.replace(src, dst)
    return text


def strip_accents(text: str) -> str:
    """Drop combining marks: 'café' -> 'cafe' (used for keys, never for display)."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def unescape(text: str) -> str:
    """Decode the HTML entities that survive feed parsing (repeatedly, for &amp;amp;)."""

    def repl(match: re.Match[str]) -> str:
        token = match.group(1)
        if token in _SIMPLE_ENTITIES:
            return _SIMPLE_ENTITIES[token]
        try:
            return chr(int(token[2:], 16)) if token.startswith("#x") else chr(int(token[1:]))
        except (ValueError, OverflowError):
            return match.group(0)

    previous = None
    for _ in range(3):
        text = _HTML_ENTITY.sub(repl, text)
        if text == previous:
            break
        previous = text
    return text


def normalize(text: str, *, casefold: bool = False, accents: bool = False) -> str:
    """Canonical form used everywhere else in the engine."""
    if not text:
        return ""
    text = unescape(fold_quotes(text))
    text = _ZERO_WIDTH.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_NL.sub("\n\n", _MULTI_SPACE.sub(" ", text))
    if accents:
        text = strip_accents(text)
    if casefold:
        text = text.casefold()
    return text.strip()


def squish(text: str) -> str:
    """One line, single spaces — for titles, slugs, labels and log messages."""
    return re.sub(r"\s+", " ", normalize(text)).strip()


def paragraphs(text: str) -> list[str]:
    """Non-empty paragraphs, normalised."""
    return [squish(chunk) for chunk in normalize(text).split("\n\n") if squish(chunk)]
