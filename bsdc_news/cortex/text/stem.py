"""A compact, dependency-free Porter stemmer (the 1980 algorithm, step by step).

Stemming is used only for *matching* (keywords, dedupe, topic keys) — never for
display, because the stems are not words. That separation is deliberate: it lets
the writer keep natural inflections while the analyser stays form-agnostic.
"""

import re

_CONSONANT_CLUSTER = re.compile(r"[^aeiou][^aeiouy]*")
_VOWEL_CLUSTER = re.compile(r"[aeiouy]+[^aeiouy]*")
_DOUBLED = re.compile(r"([bcdfglmnprstvz])\1$")
_CVC = re.compile(r"[^aeiouwxy][aeiouy][^aeiouwxy]$")


def _vowels(word: str) -> str:
    return "".join("v" if ch in "aeiouy" else "c" for ch in word)


def measure(word: str) -> int:
    """Porter's m: the number of VC sequences in the word."""
    if not word:
        return 0
    return len(re.findall(r"[aeiouy]+[^aeiouy]+", word))


def has_vowel(stem: str) -> bool:
    return any(ch in "aeiouy" for ch in stem)


def ends_double_consonant(word: str) -> bool:
    return bool(_DOUBLED.search(word))


def ends_cvc(word: str) -> bool:
    """*o condition: consonant-vowel-consonant where the last c is not w, x or y."""
    return bool(_CVC.search(word))


def _replace(word: str, suffix: str, replacement: str, min_measure: int) -> str:
    if word.endswith(suffix):
        stem = word[: -len(suffix)]
        if measure(stem) > min_measure:
            return stem + replacement
    return word


def _step1a(word: str) -> str:
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ies"):
        return word[:-2]
    if word.endswith("ss"):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def _step1b(word: str) -> str:
    if word.endswith("eed"):
        return word[:-1] if measure(word[:-3]) > 0 else word
    changed = False
    for suffix in ("ed", "ing"):
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if any(ch in "aeiouy" for ch in stem):
                word, changed = stem, True
            break
    if not changed:
        return word
    for pair in (("at", "ate"), ("bl", "ble"), ("iz", "ize")):
        if word.endswith(pair[0]):
            return word + "e"
    if ends_double_consonant(word) and word[-1] not in "lsz":
        return word[:-1]
    if measure(word) == 1 and ends_cvc(word):
        return word + "e"
    return word


def _step1c(word: str) -> str:
    if word.endswith("y") and has_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


_STEP2 = (("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
          ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"),
          ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
          ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
          ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"))

_STEP3 = (("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
          ("ical", "ic"), ("ful", ""), ("ness", ""))

_STEP4 = ("al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment",
          "ent", "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize")


def _step4(word: str) -> str:
    for suffix in _STEP4:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if suffix == "ion" and stem and stem[-1] not in "st":
                continue
            if measure(stem) > 1:
                return stem
    return word


def _step5a(word: str) -> str:
    if word.endswith("e"):
        stem = word[:-1]
        if measure(stem) > 1 or (measure(stem) == 1 and not ends_cvc(stem)):
            return stem
    return word


def _step5b(word: str) -> str:
    if measure(word) > 1 and ends_double_consonant(word) and word[-1] == "l":
        return word[:-1]
    return word


def stem(word: str) -> str:
    """Porter stem of a single lower-case word."""
    word = re.sub(r"[^a-z]", "", word.lower())
    if len(word) <= 2:
        return word
    word = _step1a(word)
    word = _step1b(word)
    word = _step1c(word)
    for suffix, replacement in _STEP2:
        word = _replace(word, suffix, replacement, 0)
    for suffix, replacement in _STEP3:
        word = _replace(word, suffix, replacement, 0)
    word = _step4(word)
    word = _step5a(word)
    return _step5b(word)


def stem_all(tokens: list[str]) -> list[str]:
    return [stem(token) for token in tokens]


def stem_index(tokens: list[str]) -> dict[str, set[str]]:
    """Map each stem back to the surface forms that produced it."""
    index: dict[str, set[str]] = {}
    for token in tokens:
        index.setdefault(stem(token), set()).add(token)
    return index


def canonical_form(tokens: list[str]) -> str:
    """Stable bag-of-stems string used for cheap duplicate detection."""
    return " ".join(sorted({stem(token) for token in tokens}))
