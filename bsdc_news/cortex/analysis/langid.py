"""Language identification from character n-gram profiles (no model download).

Needed because feeds mix English with Bengali/Arabic/Hindi items and the writer
must not try to rewrite a script it cannot handle.
"""

import re
from collections import Counter

from ..text.normalize import normalize
from ..text.tokenize import char_ngrams

SCRIPT_RANGES = {
    "bn": ((0x0980, 0x09FF),),          # Bengali
    "hi": ((0x0900, 0x097F),),          # Devanagari
    "ar": ((0x0600, 0x06FF), (0x0750, 0x077F)),
    "zh": ((0x4E00, 0x9FFF),),
    "ja": ((0x3040, 0x30FF),),
    "ko": ((0xAC00, 0xD7AF),),
    "th": ((0x0E00, 0x0E7F),),
    "ru": ((0x0400, 0x04FF),),
    "el": ((0x0370, 0x03FF),),
    "he": ((0x0590, 0x05FF),),
    "ta": ((0x0B80, 0x0BFF),),
}

FUNCTION_WORDS = {
    "en": {"the", "and", "of", "to", "in", "is", "that", "for", "with", "as", "was", "on", "be", "by", "it"},
    "es": {"de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las", "por", "un", "para", "con"},
    "fr": {"le", "de", "et", "à", "les", "des", "en", "un", "du", "une", "que", "est", "pour", "qui", "dans"},
    "de": {"der", "die", "und", "in", "den", "von", "zu", "das", "mit", "sich", "des", "auf", "für", "ist", "im"},
    "pt": {"de", "a", "o", "que", "e", "do", "da", "em", "um", "para", "com", "não", "uma", "os", "no"},
    "id": {"yang", "dan", "di", "itu", "untuk", "pada", "ke", "para", "merupakan", "atau", "dalam", "oleh", "ini", "akan"},
    "tr": {"bir", "ve", "bu", "da", "de", "ile", "mi", "için", "gibi", "daha", "çok", "kadar", "sonra", "ancak"},
    "bn": {"এবং", "একটি", "এই", "যে", "করে", "হয়", "থেকে", "জন্য", "সঙ্গে", "তাঁর"},
    "hi": {"और", "का", "के", "की", "है", "में", "से", "को", "एक", "यह"},
    "ar": {"من", "في", "و", "أن", "على", "إلى", "هذا", "التي", "هو", "عن"},
}


def script_of(text: str) -> str:
    """Dominant non-Latin script, or '' for Latin text."""
    counts: Counter = Counter()
    for ch in text:
        point = ord(ch)
        for language, ranges in SCRIPT_RANGES.items():
            if any(low <= point <= high for low, high in ranges):
                counts[language] += 1
                break
    if not counts:
        return ""
    language, count = counts.most_common(1)[0]
    return language if count >= max(3, len(text) * 0.05) else ""


def detect(text: str) -> tuple[str, float]:
    """Return (language, confidence)."""
    text = normalize(text)[:4000]
    if not text.strip():
        return "en", 0.0
    script = script_of(text)
    if script:
        return script, 0.95
    tokens = re.findall(r"[a-zà-ÿ']+", text.lower())
    if not tokens:
        return "en", 0.3
    scores: dict[str, float] = {}
    token_set = set(tokens)
    for language, vocabulary in FUNCTION_WORDS.items():
        overlap = len(token_set & vocabulary)
        scores[language] = overlap / max(1, min(len(tokens), 200))
    profile = char_ngrams(text, 3)
    language = max(scores, key=lambda key: (scores[key], key)) if any(scores.values()) else "en"
    confidence = min(0.99, 0.35 + scores.get(language, 0.0) * 6 + (0.25 if profile else 0.0))
    if scores.get("en", 0.0) == 0.0 and confidence < 0.5:
        return "en", 0.4
    return language, round(confidence, 3)


def is_supported(text: str, *, supported: tuple[str, ...] = ("en",)) -> bool:
    return detect(text)[0] in supported


def transliterate_basic(text: str) -> str:
    """Strip non-Latin characters for slug/label use (never for display)."""
    return re.sub(r"[^\x00-\x7f]+", " ", text)
