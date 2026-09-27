"""Syllable counting for readability formulas — heuristic, but calibrated.

Flesch/Flesch-Kincaid/SMOG all need syllables per word. A vowel-group count
with silent-e, -ed and diphthong corrections tracks a dictionary count closely
enough for editorial decisions and costs nothing.
"""

import re

_VOWEL_GROUP = re.compile(r"[aeiouy]+")
_SILENT_E = re.compile(r"e$")
_LE_END = re.compile(r"[^aeiouy]le$")
_DIAERESIS = re.compile(r"(?:([aeiouy])(?=\1))")


def syllables(word: str) -> int:
    """Estimate the syllable count of one English word (>= 1)."""
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    word = _DIAERESIS.sub(r"\1", word)
    # "-ed" is silent unless preceded by t/d ("wanted" = 2, "walked" = 1).
    if word.endswith("ed") and len(word) > 3 and word[-3] not in "td":
        word = word[:-2]
    groups = len(_VOWEL_GROUP.findall(word))
    if _LE_END.search(word):
        groups += 0            # "-le" already counted by the vowel group
    elif _SILENT_E.search(word) and groups > 1 and not word.endswith(("ee", "ie", "ye", "oe")):
        groups -= 1
    return max(1, groups)


def syllable_count(text: str) -> int:
    return sum(syllables(word) for word in re.findall(r"[A-Za-z']+", text or ""))


def polysyllables(text: str) -> int:
    """Words of three or more syllables (used by SMOG and Gunning Fog)."""
    return sum(1 for word in re.findall(r"[A-Za-z']+", text or "") if syllables(word) >= 3)


def words_with_syllables(text: str) -> list[tuple[str, int]]:
    return [(word, syllables(word)) for word in re.findall(r"[A-Za-z']+", text or "")]


def average_syllables(text: str) -> float:
    pairs = words_with_syllables(text)
    if not pairs:
        return 0.0
    return sum(count for _, count in pairs) / len(pairs)
