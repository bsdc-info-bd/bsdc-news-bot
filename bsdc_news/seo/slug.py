"""Slug and Blogger URL derivation.

Blogger builds post URLs from the title, so a bad title means a bad URL forever.
This module produces a slug that is short, lowercase, hyphenated, keyword-led,
free of stopwords and diacritics, transliterated for Bangla titles, and unique
against previously published slugs.
"""

import re
import unicodedata

from ..cortex.text.normalize import squish
from ..cortex.text.stopwords import is_stopword

MAX_WORDS = 7
MAX_LENGTH = 60
_SEPARATOR = "-"
_BANGLA_VOWELS = {
    "অ": "o", "আ": "a", "ই": "i", "ঈ": "i", "উ": "u", "ঊ": "u", "ঋ": "ri",
    "এ": "e", "ঐ": "oi", "ও": "o", "ঔ": "ou",
}
_BANGLA_CONSONANTS = {
    "ক": "k", "খ": "kh", "গ": "g", "ঘ": "gh", "ঙ": "ng", "চ": "ch", "ছ": "chh",
    "জ": "j", "ঝ": "jh", "ঞ": "n", "ট": "t", "ঠ": "th", "ড": "d", "ঢ": "dh",
    "ণ": "n", "ত": "t", "থ": "th", "দ": "d", "ধ": "dh", "ন": "n", "প": "p",
    "ফ": "f", "ব": "b", "ভ": "v", "ম": "m", "য": "j", "র": "r", "ল": "l",
    "শ": "sh", "ষ": "sh", "স": "s", "হ": "h", "ড়": "r", "ঢ়": "rh", "য়": "y",
    "ৎ": "t", "ং": "ng", "ঃ": "h", "ঁ": "n",
}
_BANGLA_DIGITS = {"০": "0", "১": "1", "২": "2", "৩": "3", "৪": "4", "৫": "5",
                  "৬": "6", "৭": "7", "৮": "8", "৯": "9"}
# Vowel signs (matras) carry the sound a consonant is actually pronounced with, and the
# hasanta (্) cancels it. Without them "বাংলাদেশ" transliterated to "b ngl d sh".
_BANGLA_MATRAS = {"া": "a", "ি": "i", "ী": "i", "ু": "u", "ূ": "u", "ৄ": "ri", "ে": "e",
                  "ৈ": "oi", "ো": "o", "ৌ": "ou", "ৃ": "ri"}
_BANGLA_HASANTA = "্"
_BANGLA_SIGNS = {"ং": "ng", "ঃ": "h", "ঁ": "n"}   # ং = the "ng" in bangla/bangladesh


def transliterate(text: str) -> str:
    """Bangla (and accented Latin) to ASCII, so URLs stay crawlable everywhere."""
    out: list[str] = []
    for ch in text:
        if ch == _BANGLA_HASANTA:
            continue                                   # cancels the inherent vowel
        if ch in _BANGLA_MATRAS or ch in _BANGLA_SIGNS:
            out.append(_BANGLA_MATRAS.get(ch) or _BANGLA_SIGNS[ch])
            continue
        if ch in _BANGLA_CONSONANTS or ch in _BANGLA_VOWELS or ch in _BANGLA_DIGITS:
            out.append(_BANGLA_CONSONANTS.get(ch) or _BANGLA_VOWELS.get(ch) or _BANGLA_DIGITS[ch])
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        ascii_char = decomposed.encode("ascii", "ignore").decode()
        out.append(ascii_char if ascii_char else (" " if not ch.isalnum() else ""))
    return squish("".join(out))


def keywords_in(text: str, *, keep_digits: bool = True) -> list[str]:
    """Slug-worthy tokens: no stopwords, no punctuation, keywords first."""
    text = transliterate(text or "").lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    out: list[str] = []
    for token in tokens:
        if not keep_digits and token.isdigit():
            continue
        if len(token) < 2 or is_stopword(token):
            continue
        if token in out:
            continue
        out.append(token)
    return out


def build(title: str, *, keyword: str = "", max_words: int = MAX_WORDS,
          max_length: int = MAX_LENGTH, keep_year: bool = True) -> str:
    """A clean slug from a title, biased towards the primary keyword."""
    tokens = keywords_in(title)
    if keyword:
        wanted = [token for token in keywords_in(keyword)]
        tokens = [token for token in wanted if token in tokens] + \
                 [token for token in tokens if token not in wanted]
    if not keep_year:
        tokens = [token for token in tokens if not re.fullmatch(r"(19|20)\d{2}", token)]
    tokens = tokens[:max_words]
    slug = _SEPARATOR.join(tokens)
    if len(slug) > max_length:
        while tokens and len(_SEPARATOR.join(tokens)) > max_length:
            tokens.pop()
        slug = _SEPARATOR.join(tokens)
    return slug or "article"


def unique(slug: str, published: list[str] | None = None, *, limit: int = 40) -> str:
    """Append a counter until the slug is not already taken."""
    published = {item.strip("/").lower() for item in (published or []) if item}
    if not slug:
        return "article"
    if slug not in published:
        return slug
    for index in range(2, limit):
        candidate = f"{slug}-{index}"
        if candidate not in published:
            return candidate
    return f"{slug}-{abs(hash(slug)) % 10000}"


def from_url(url: str) -> str:
    """Read the slug back out of a published Blogger URL."""
    path = squish(url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if not path:
        return ""
    tail = path.rsplit("/", 1)[-1]
    if tail.endswith(".html"):
        tail = tail[: -len(".html")]
    return tail.replace("_", "-").lower()


def audit(slug: str) -> list[tuple[str, bool, str]]:
    """Slug quality checks for the SEO report."""
    checks = [
        ("slug_length", 1 <= len(slug) <= MAX_LENGTH, f"{len(slug)} characters"),
        ("slug_lowercase", slug == slug.lower(), "must be lowercase"),
        ("slug_separators", " " not in slug and "_" not in slug, "hyphens only"),
        ("slug_stopwords", not any(is_stopword(part) for part in slug.split("-")),
         "no stopwords"),
        ("slug_ascii", slug.isascii(), "ASCII only"),
        ("slug_words", 2 <= len(slug.split("-")) <= MAX_WORDS + 2,
         f"{len(slug.split('-'))} words"),
    ]
    return checks


def breadcrumb_path(slug: str, category: str = "", *, base: str = "") -> str:
    """A readable path for breadcrumb markup."""
    parts = [part for part in (base.rstrip("/"), category.lower().replace(" ", "-"), slug) if part]
    path = "/".join(parts)
    # An absolute site URL must stay absolute: "/https://b.test/…" is not a path.
    return path if path.startswith(("http://", "https://")) else "/" + path
