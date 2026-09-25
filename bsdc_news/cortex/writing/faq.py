"""FAQ generation grounded in the source text.

Questions come from the bundled patterns plus question sentences already present
in the source. Answers are assembled from source sentences; a question with no
supporting sentence is dropped rather than answered with a guess, because an
invented answer in FAQ schema is a structured-data violation.
"""

import re

from ..lexicon import loader
from ..semantic.similarity import token_similarity
from ..text.normalize import squish
from ..text.sentences import split_sentences
from ..text.stopwords import is_stopword
from ..types import Fact

MAX_ITEMS = 6


def source_casing(source: str, phrase: str) -> str:
    """Write a normalised keyphrase the way the article does ("rubin ultra" -> "Rubin Ultra")."""
    if not phrase or phrase in source:
        return phrase
    index = source.lower().find(phrase.lower())
    if index < 0:
        words = phrase.split()
        return " ".join(word[:1].upper() + word[1:] if word.islower() else word for word in words)
    return source[index:index + len(phrase)]
MIN_ANSWER_WORDS = 12
MAX_ANSWER_WORDS = 55


def questions(source: str, *, subject: str = "", limit: int = MAX_ITEMS) -> list[str]:
    """Candidate questions: patterns instantiated with the subject, plus source questions."""
    out: list[str] = []
    for match in re.finditer(r"([^.!?\n]{8,110}\?)", source or ""):
        text = squish(match.group(1))
        if text.endswith("?") and len(text.split()) >= 4:
            out.append(text)
    if subject:
        source_lower = (source or "").lower()
        subject = source_casing(source or "", subject)
        for pattern in loader.faq_patterns():
            try:
                text = squish(pattern.format(subject=subject))
            except (KeyError, IndexError):
                continue
            # A pattern that names something the article never mentions (a country, a
            # competitor) would produce a question this source cannot answer.
            literals = [word for word in re.findall(r"\b[A-Z][a-z]{4,}", pattern)
                        if word not in {"What", "Which", "Where", "When", "Why", "How"}]
            # Domain words in the pattern ("devices", "app", "battery") must appear in the
            # source too, or the question is about a product story this article is not.
            literals += [word for word in re.findall(r"\b[a-z]{5,}\b", pattern)
                         if not is_stopword(word) and word not in ("subject",)]
            if any(word.lower() not in source_lower for word in literals):
                continue
            if text not in out:
                out.append(text)
    seen: list[str] = []
    for item in out:
        if any(token_similarity(item, other) > 0.78 for other in seen):
            continue
        seen.append(item)
        if len(seen) >= limit * 2:
            break
    return seen


def answer(question: str, *, sentences: list[str], facts: list[Fact],
           min_similarity: float = 0.30) -> str:
    """Build an answer from the sentences that best match the question.

    An answer must share a content word with the question; otherwise the pair is
    dropped, because a wrong answer inside FAQ schema is worse than no answer.
    """
    tokens = {token for token in re.findall(r"[a-z]{4,}", question.lower())
              if not is_stopword(token)}
    scored: list[tuple[float, str]] = []
    for sentence in sentences:
        text = squish(sentence)
        if len(text.split()) < MIN_ANSWER_WORDS // 2:
            continue
        overlap = len(tokens & {token for token in re.findall(r"[a-z]{4,}", text.lower())
                                if not is_stopword(token)})
        if not overlap:
            continue                       # no shared content word: not an answer
        similarity = token_similarity(question, text)
        value = max(similarity, overlap / max(1, len(tokens)) * 0.9)
        if value >= min_similarity:
            scored.append((value, text))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    if not scored:
        return ""
    answer_text = scored[0][1]
    for _, extra in scored[1:3]:
        if token_similarity(answer_text, extra) > 0.6:
            continue
        if len(answer_text.split()) + len(extra.split()) > MAX_ANSWER_WORDS:
            break
        if answer_text.endswith((".", "!", "?")):
            answer_text = f"{answer_text} {extra}"
        else:
            answer_text = f"{answer_text.rstrip('.')}. {extra}"
    words = answer_text.split()
    if len(words) > MAX_ANSWER_WORDS:
        answer_text = " ".join(words[:MAX_ANSWER_WORDS]).rstrip(",;:") + "."
    return tidy(squish(answer_text))


def tidy(text: str) -> str:
    """Never publish an answer that stops mid-clause.

    Sentences lifted from a truncated fact can end on a comma, which reads like a
    mistake in the FAQ block and in the FAQPage schema.
    """
    text = squish(text).rstrip()
    if not text or text[-1] in ".!?":
        return text
    cut = max(text.rfind(". "), text.rfind("; "))
    if cut > len(text) * 0.4:
        return text[:cut + 1]
    return text.rstrip(",;:-—") + "."


def build(source: str, *, subject: str = "", facts: list[Fact] | None = None,
          limit: int = MAX_ITEMS) -> list[tuple[str, str]]:
    """Question/answer pairs with answers that the source actually supports."""
    facts = facts or []
    sentences = split_sentences(source or "")
    sentences += [squish(fact.text) for fact in facts if fact.text not in sentences]
    out: list[tuple[str, str]] = []
    for question in questions(source, subject=subject, limit=limit):
        answer_text = answer(question, sentences=sentences, facts=facts)
        if len(answer_text.split()) < MIN_ANSWER_WORDS:
            continue
        if any(token_similarity(question, existing) > 0.8 for existing, _ in out):
            continue
        if any(token_similarity(answer_text, existing) > 0.75 for _, existing in out):
            continue                       # one fact cannot answer three questions
        out.append((question, answer_text))
        if len(out) >= limit:
            break
    return out


def unanswered(source: str, *, subject: str = "") -> list[str]:
    """Questions readers ask that this source cannot answer — useful for follow-ups."""
    sentences = split_sentences(source or "")
    return [question for question in questions(source, subject=subject, limit=12)
            if len(answer(question, sentences=sentences, facts=[]).split()) < MIN_ANSWER_WORDS]
