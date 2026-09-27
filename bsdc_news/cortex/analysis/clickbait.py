"""Clickbait, sensationalism and thin-content detection.

The publisher refuses to amplify bait: this module scores a headline *before* it
is used, and the writer picks a different formulation when the score is high.
"""

import re

from ..text.sentences import split_sentences
from ..text.tokenize import words

CURIOSITY_GAP = (
    "you won't believe", "you will not believe", "this one trick", "one weird trick",
    "shocking", "shocked", "unbelievable", "insane", "mind-blowing", "mind blowing",
    "jaw-dropping", "jaw dropping", "you need to see", "wait until", "wait till",
    "the reason why", "here's why", "here is why", "here's what", "what happens next",
    "this is what", "no one expected", "nobody expected", "did not see that coming",
    "secret", "secrets", "hidden truth", "the truth about", "exposed", "revealed:",
    "leaked:", "what they don't", "what they do not", "don't tell", "do not tell",
)
HYPE_WORDS = {
    "insane": 1.0, "crazy": 0.8, "unbelievable": 1.0, "shocking": 1.0, "amazing": 0.5,
    "incredible": 0.7, "epic": 0.8, "mind-blowing": 1.0, "jaw-dropping": 1.0,
    "game-changer": 0.9, "gamechanging": 0.9, "revolutionary": 0.7, "groundbreaking": 0.6,
    "massive": 0.5, "huge": 0.4, "enormous": 0.5, "colossal": 0.7, "unprecedented": 0.6,
    "historic": 0.4, "explosive": 0.7, "bombshell": 1.0, "stunning": 0.7, "wild": 0.6,
    "absurd": 0.6, "ridiculous": 0.6, "brutal": 0.6, "devastating": 0.7, "catastrophic": 0.8,
    "apocalyptic": 0.9, "nightmare": 0.7, "disaster": 0.6, "doomed": 0.8, "dead": 0.5,
    "killer": 0.6, "deadly": 0.6, "terrifying": 0.8, "scary": 0.5, "fear": 0.4,
    "panic": 0.7, "urgent": 0.6, "breaking": 0.3, "exclusive": 0.3, "must-see": 0.8,
    "must-read": 0.7, "best-ever": 0.8, "greatest": 0.5, "ultimate": 0.5, "perfect": 0.4,
    "free-forever": 0.6, "never-again": 0.7, "stop-doing": 0.7, "warning": 0.5,
}
URGENCY = ("now", "today only", "limited time", "act fast", "hurry", "before it's gone",
           "before it is gone", "last chance", "don't miss", "do not miss", "ends soon",
           "hours left", "minutes left", "immediately", "right now", "asap")
LISTICLE_HINT = re.compile(r"^\s*(?:\d{1,3}\s*(?:\+|ways|things|tips|tricks|reasons|facts|photos|pictures|secrets|mistakes|apps|gadgets|deals))\b", re.IGNORECASE)
ALL_CAPS = re.compile(r"\b[A-Z]{4,}\b")
_QUESTION_BAIT = re.compile(r"\?\s*$")


def score_headline(headline: str) -> tuple[float, list[str]]:
    """0..1 clickbait score plus the reasons. >= 0.55 should be rewritten."""
    if not headline:
        return 1.0, ["empty headline"]
    lowered = headline.lower()
    tokens = words(headline)
    reasons: list[str] = []
    score = 0.0
    for phrase in CURIOSITY_GAP:
        if phrase in lowered:
            score += 0.34
            reasons.append(f"curiosity gap: '{phrase}'")
            break
    for token in tokens:
        weight = HYPE_WORDS.get(token.replace("-", ""), 0.0)
        if weight:
            score += weight * 0.22
            reasons.append(f"hype word: '{token}'")
    for phrase in URGENCY:
        if phrase in lowered:
            score += 0.2
            reasons.append(f"urgency: '{phrase}'")
            break
    if LISTICLE_HINT.match(headline):
        score += 0.18
        reasons.append("listicle headline")
    caps = ALL_CAPS.findall(headline)
    if caps:
        score += min(0.25, 0.12 * len(caps))
        reasons.append(f"shouting caps: {', '.join(caps[:3])}")
    if headline.count("!") >= 1:
        score += 0.12 * headline.count("!")
        reasons.append("exclamation marks")
    if _QUESTION_BAIT.search(headline) and not any(ch.isdigit() for ch in headline):
        score += 0.08
        reasons.append("rhetorical question")
    if len(tokens) > 22:
        score += 0.1
        reasons.append("over-long headline")
    if len(tokens) < 4:
        score += 0.12
        reasons.append("vague headline")
    return round(min(1.0, score), 3), reasons[:6]


def is_clickbait(headline: str, *, threshold: float = 0.55) -> bool:
    return score_headline(headline)[0] >= threshold


def body_score(text: str) -> dict:
    """Thin-content / bait-body signals for the quality gate."""
    sentences = split_sentences(text)
    tokens = words(text)
    hype = sum(HYPE_WORDS.get(token, 0.0) for token in tokens)
    questions = sum(1 for sentence in sentences if sentence.strip().endswith("?"))
    return {
        "sentences": len(sentences),
        "words": len(tokens),
        "hype_load": round(hype / max(1, len(tokens)) * 100, 2),
        "question_share": round(questions / max(1, len(sentences)), 3),
        "thin": len(tokens) < 180,
        "exclamation_density": round(text.count("!") / max(1, len(tokens)) * 100, 3),
    }


def sanitize_headline(headline: str) -> str:
    """Remove shouting and trailing bait punctuation (never changes the facts)."""
    cleaned = re.sub(r"\s*!+\s*$", "", headline.strip())
    cleaned = ALL_CAPS.sub(lambda m: m.group(0).title() if m.group(0) not in
                           {"USA", "UK", "AI", "API", "CEO", "GPU", "CPU", "iOS", "US", "EU", "TV", "VR", "AR"} else m.group(0), cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip(" -—:|")
