"""Seven readability formulas plus a web-reading score.

News that ranks is news people finish: every formula here feeds the quality gate
and the automatic simplifier.
"""

import math
import re

from ..text.sentences import split_sentences
from ..text.stopwords import ENGLISH
from ..text.syllables import polysyllables, syllable_count
from ..text.tokenize import words

_WORD = re.compile(r"[A-Za-z']+")


def counts(text: str) -> dict[str, int]:
    sentences = split_sentences(text)
    tokens = words(text)
    letters = _WORD.findall(text)
    return {
        "sentences": max(1, len(sentences)),
        "words": max(1, len(tokens)),
        "letters": len(letters),
        "syllables": syllable_count(text),
        "polysyllables": polysyllables(text),
        "characters": len(text),
        "long_words": sum(1 for token in tokens if len(token) > 7),
        "complex_words": sum(1 for token in tokens if len(token) > 2 and token.endswith(("tion", "sion", "ment", "ance", "ence", "ity"))),
        "stopwords": sum(1 for token in tokens if token in ENGLISH),
    }


def flesch_reading_ease(c: dict) -> float:
    """0-100; 60-70 is standard news prose."""
    return round(206.835 - 1.015 * (c["words"] / c["sentences"])
                 - 84.6 * (c["syllables"] / c["words"]), 2)


def flesch_kincaid_grade(c: dict) -> float:
    return round(0.39 * (c["words"] / c["sentences"]) + 11.8 * (c["syllables"] / c["words"]) - 15.59, 2)


def gunning_fog(c: dict) -> float:
    return round(0.4 * ((c["words"] / c["sentences"]) + 100 * (c["polysyllables"] / c["words"])), 2)


def smog(c: dict) -> float:
    if c["sentences"] < 3:
        return 0.0
    return round(1.0430 * math.sqrt(c["polysyllables"] * (30 / c["sentences"])) + 3.1291, 2)


def ari(c: dict) -> float:
    return round(4.71 * (c["characters"] / c["words"]) + 0.5 * (c["words"] / c["sentences"]) - 21.43, 2)


def coleman_liau(c: dict) -> float:
    l_index = (c["letters"] / c["words"]) * 100
    s_index = (c["sentences"] / c["words"]) * 100
    return round(0.0588 * l_index - 0.296 * s_index - 15.8, 2)


def dale_chall_approx(c: dict) -> float:
    """Dale-Chall without the 3k-word list: long words proxy for unfamiliar ones."""
    unfamiliar = c["long_words"] / c["words"] * 100
    return round(0.1579 * unfamiliar + 0.0496 * (c["words"] / c["sentences"]) + 3.6365, 2)


def web_readability(text: str) -> dict:
    """Paragraph/sentence rhythm metrics that matter more on screens."""
    paragraphs = [chunk for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    sentences = split_sentences(text)
    lengths = [len(words(sentence)) for sentence in sentences]
    paragraph_lengths = [len(words(paragraph)) for paragraph in paragraphs]
    return {
        "paragraphs": len(paragraphs),
        "avg_paragraph_words": round(sum(paragraph_lengths) / max(1, len(paragraph_lengths)), 1),
        "max_paragraph_words": max(paragraph_lengths) if paragraph_lengths else 0,
        "avg_sentence_words": round(sum(lengths) / max(1, len(lengths)), 1),
        "max_sentence_words": max(lengths) if lengths else 0,
        "short_sentence_share": round(sum(1 for n in lengths if n <= 14) / max(1, len(lengths)), 3),
        "long_sentence_share": round(sum(1 for n in lengths if n >= 28) / max(1, len(lengths)), 3),
    }


def grade_band(grade: float) -> str:
    if grade <= 6:
        return "very easy"
    if grade <= 9:
        return "easy"
    if grade <= 12:
        return "standard"
    if grade <= 16:
        return "difficult"
    return "academic"


def analyze(text: str) -> dict:
    """All formulas at once, plus a 0-100 readability score for the quality gate."""
    c = counts(text)
    fre = flesch_reading_ease(c)
    grades = [flesch_kincaid_grade(c), gunning_fog(c), ari(c), coleman_liau(c)]
    grades = [grade for grade in grades if grade > 0]
    average_grade = round(sum(grades) / len(grades), 2) if grades else 0.0
    web = web_readability(text)
    score = 0.0
    score += max(0.0, min(45.0, (fre - 20) * 0.9))            # ease contributes up to 45
    score += max(0.0, 20.0 - abs(average_grade - 9.5) * 2.2)  # grade 8-11 is the sweet spot
    score += 15.0 if web["avg_paragraph_words"] <= 70 else max(0.0, 15 - (web["avg_paragraph_words"] - 70) * 0.3)
    score += 12.0 * web["short_sentence_share"]
    score += 8.0 * (1 - min(1.0, web["long_sentence_share"] * 3))
    return {
        "counts": c,
        "flesch_reading_ease": fre,
        "flesch_kincaid_grade": flesch_kincaid_grade(c),
        "gunning_fog": gunning_fog(c),
        "smog": smog(c),
        "ari": ari(c),
        "coleman_liau": coleman_liau(c),
        "dale_chall_approx": dale_chall_approx(c),
        "average_grade": average_grade,
        "band": grade_band(average_grade),
        "web": web,
        "score": round(max(0.0, min(100.0, score))),
    }


def hardest_sentences(text: str, *, top: int = 3) -> list[tuple[str, float]]:
    """The least readable sentences — what the simplifier attacks first."""
    scored = []
    for sentence in split_sentences(text):
        c = counts(sentence)
        scored.append((sentence, round(flesch_reading_ease(c), 2)))
    scored.sort(key=lambda pair: pair[1])
    return scored[:top]
