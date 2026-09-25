"""Lexicon sentiment with negation, intensifiers and contrast handling.

Scores a document, a sentence and an entity co-occurrence map, which the writer
uses to keep the tone factual ("prices fell" not "disastrous prices collapsed").
"""

from dataclasses import dataclass

from ..text.sentences import split_sentences
from ..text.tokenize import words

POSITIVE = {
    "good": 1.0, "great": 1.6, "excellent": 2.0, "amazing": 1.8, "strong": 1.2,
    "record": 1.3, "growth": 1.1, "grows": 1.0, "grew": 1.0, "gain": 1.1, "gains": 1.1,
    "rise": 1.0, "rises": 1.0, "rose": 1.0, "boost": 1.2, "boosts": 1.2, "improve": 1.2,
    "improves": 1.2, "improved": 1.2, "improvement": 1.3, "faster": 1.0, "speed": 0.6,
    "efficient": 1.1, "efficiency": 1.0, "cheaper": 0.9, "affordable": 1.0, "free": 1.0,
    "launch": 0.6, "launches": 0.6, "unveil": 0.7, "unveils": 0.7, "unveiled": 0.7,
    "release": 0.5, "released": 0.5, "upgrade": 1.0, "upgrades": 1.0, "win": 1.2,
    "wins": 1.2, "won": 1.2, "success": 1.5, "successful": 1.4, "profit": 1.3,
    "profits": 1.3, "revenue": 0.8, "beat": 1.1, "beats": 1.1, "exceeds": 1.0,
    "innovation": 1.2, "innovative": 1.2, "breakthrough": 1.6, "popular": 1.0,
    "support": 0.7, "supports": 0.7, "safe": 0.9, "secure": 0.9, "reliable": 1.0,
    "stable": 0.8, "clear": 0.5, "easy": 0.7, "simple": 0.5, "best": 1.6, "top": 0.9,
    "lead": 0.9, "leads": 0.9, "leading": 0.9, "leader": 0.9, "expand": 0.9,
    "expands": 0.9, "expansion": 0.9, "partnership": 0.9, "deal": 0.6, "agree": 0.6,
    "agrees": 0.6, "approved": 0.7, "approval": 0.7, "hope": 0.8, "optimistic": 1.1,
    "confident": 0.9, "happy": 1.3, "pleased": 1.0, "love": 1.4, "loved": 1.3,
    "praise": 1.1, "praised": 1.1, "award": 1.3, "awarded": 1.3, "milestone": 1.1,
}
NEGATIVE = {
    "bad": -1.2, "poor": -1.1, "weak": -1.0, "slow": -0.9, "slower": -0.9,
    "delay": -1.1, "delays": -1.1, "delayed": -1.1, "postpone": -1.0, "postponed": -1.0,
    "cancel": -1.2, "cancelled": -1.2, "canceled": -1.2, "cut": -0.9, "cuts": -0.9,
    "layoff": -1.6, "layoffs": -1.6, "job cuts": -1.6, "loss": -1.3, "losses": -1.3,
    "lost": -1.0, "lose": -1.0, "loses": -1.0, "fall": -0.9, "falls": -0.9, "fell": -0.9,
    "drop": -0.9, "drops": -0.9, "dropped": -0.9, "decline": -1.1, "declines": -1.1,
    "crash": -1.8, "crashed": -1.8, "crisis": -1.7, "disaster": -1.8, "fail": -1.4,
    "fails": -1.4, "failed": -1.4, "failure": -1.5, "bug": -1.0, "bugs": -1.0,
    "glitch": -0.9, "error": -0.9, "errors": -0.9, "flaw": -1.1, "flaws": -1.1,
    "vulnerability": -1.3, "vulnerabilities": -1.3, "exploit": -1.2, "exploits": -1.2,
    "exploited": -1.3, "hack": -1.4, "hacked": -1.5, "hacker": -1.2, "hackers": -1.2,
    "breach": -1.5, "breached": -1.5, "leak": -1.2, "leaked": -1.2, "leaks": -1.2,
    "scam": -1.8, "fraud": -1.8, "theft": -1.5, "steal": -1.4, "stolen": -1.4,
    "attack": -1.5, "attacks": -1.5, "attacked": -1.5, "malware": -1.5, "ransomware": -1.8,
    "phishing": -1.4, "spam": -1.1, "ban": -1.2, "banned": -1.3, "block": -0.9,
    "blocked": -1.0, "restrict": -0.8, "restricted": -0.8, "fine": -1.0, "fined": -1.2,
    "penalty": -1.2, "penalties": -1.2, "lawsuit": -1.4, "sues": -1.4, "sued": -1.4,
    "litigation": -1.2, "probe": -1.0, "investigation": -1.1, "investigations": -1.1,
    "accusation": -1.3, "allegation": -1.3, "alleged": -1.1, "allegedly": -1.1,
    "complaint": -1.0, "complaints": -1.0, "concern": -0.8, "concerns": -0.8,
    "concerned": -0.8, "worry": -0.9, "worried": -1.0, "risk": -1.0, "risks": -1.0,
    "risky": -1.1, "threat": -1.3, "threats": -1.3, "danger": -1.3, "dangerous": -1.4,
    "damage": -1.3, "damaged": -1.3, "broken": -1.2, "broke": -0.8, "problem": -1.0,
    "problems": -1.0, "issue": -0.8, "issues": -0.8, "outage": -1.5, "recall": -1.4,
    "recalled": -1.4, "warning": -1.0, "warns": -1.0, "warned": -1.0, "criticism": -1.2,
    "criticised": -1.2, "criticized": -1.2, "backlash": -1.5, "outrage": -1.6,
    "controversy": -1.3, "controversial": -1.2, "expensive": -0.8, "costly": -1.0,
    "pricey": -0.8, "worst": -1.8, "deadly": -2.0, "dead": -1.6, "death": -1.7,
    "deaths": -1.7, "injury": -1.4, "injured": -1.4, "kill": -1.9, "killed": -1.9,
    "shutdown": -1.4, "shut down": -1.3, "bankrupt": -2.0, "bankruptcy": -2.0,
    "debt": -1.1, "deficit": -1.2, "recession": -1.6, "inflation": -1.1, "shortage": -1.2,
    "scandal": -1.8, "abuse": -1.8, "harassment": -1.7, "discrimination": -1.5,
    "misleading": -1.3, "deceptive": -1.4, "false": -1.1, "fake": -1.3, "hoax": -1.4,
    "reject": -1.0, "rejected": -1.0, "deny": -0.8, "denies": -0.8, "denied": -0.8,
    "refuse": -0.9, "refused": -0.9, "regret": -1.0, "apologise": -0.9, "apologize": -0.9,
    "apology": -0.9, "sad": -1.3, "angry": -1.4, "furious": -1.7, "frustrated": -1.1,
    "disappointed": -1.2, "unhappy": -1.2, "annoying": -1.0, "confusing": -0.9,
    "complicated": -0.6, "difficult": -0.8, "hard": -0.5, "struggle": -1.1,
    "struggles": -1.1, "struggling": -1.2, "underperform": -1.1, "miss": -0.9,
    "misses": -0.9, "missed": -0.9, "below": -0.5, "downgrade": -1.2, "downgraded": -1.2,
}
INTENSIFIERS = {"very": 1.5, "really": 1.4, "extremely": 1.8, "incredibly": 1.7,
                "absolutely": 1.7, "totally": 1.5, "completely": 1.5, "highly": 1.5,
                "significantly": 1.6, "substantially": 1.5, "dramatically": 1.7,
                "sharply": 1.5, "steeply": 1.5, "far": 1.3, "much": 1.3, "so": 1.2,
                "slightly": 0.6, "somewhat": 0.7, "barely": 0.4, "hardly": 0.4,
                "marginally": 0.5, "mildly": 0.6, "a bit": 0.6, "quite": 1.2}
NEGATORS = {"not", "no", "never", "none", "neither", "nor", "nothing", "nobody",
            "nowhere", "hardly", "barely", "scarcely", "seldom", "rarely", "without",
            "lack", "lacks", "lacking", "avoid", "avoids", "refuse", "refuses", "fail",
            "fails", "failed", "cannot", "cant", "wont", "isnt", "arent", "wasnt",
            "werent", "doesnt", "dont", "didnt", "hasnt", "havent", "hadnt"}
CONTRAST = {"but", "however", "although", "though", "yet", "despite", "whereas",
            "instead", "nevertheless", "nonetheless", "while"}


@dataclass
class Sentiment:
    score: float                 # -1..1
    label: str                   # positive | neutral | negative | mixed
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    intensity: float = 0.0       # absolute magnitude
    per_sentence: list[float] = None  # type: ignore[assignment]
    top_positive: list[str] = None    # type: ignore[assignment]
    top_negative: list[str] = None    # type: ignore[assignment]

    def as_dict(self) -> dict:
        return {"score": round(self.score, 4), "label": self.label,
                "positive_hits": self.positive, "negative_hits": self.negative,
                "neutral": self.neutral, "intensity": round(self.intensity, 4)}


def _window_score(tokens: list[str]) -> tuple[float, list[str], list[str]]:
    """Score one sentence with negation, intensifiers and contrast damping."""
    total = 0.0
    positives: list[str] = []
    negatives: list[str] = []
    negation_depth = 0
    damping = 1.0
    for index, token in enumerate(tokens):
        lowered = token.lower().replace("'", "")
        if lowered in CONTRAST:
            damping = 0.55          # after "but" the polarity is the real message
            continue
        if lowered in NEGATORS or lowered.endswith("nt"):
            negation_depth = 3
            continue
        intensifier = INTENSIFIERS.get(lowered)
        if intensifier is not None:
            continue
        value = POSITIVE.get(lowered, NEGATIVE.get(lowered, 0.0))
        if not value and index:
            bigram = f"{tokens[index - 1].lower()} {lowered}"
            value = POSITIVE.get(bigram, NEGATIVE.get(bigram, 0.0))
        if not value:
            negation_depth = max(0, negation_depth - 1)
            continue
        multiplier = 1.0
        if index:
            previous = tokens[index - 1].lower()
            multiplier *= INTENSIFIERS.get(previous, 1.0)
        if negation_depth:
            value = -value * 0.85
        total += value * multiplier * damping
        (positives if value > 0 else negatives).append(lowered)
        negation_depth = max(0, negation_depth - 1)
    return total, positives, negatives


def analyze(text: str, *, per_sentence: bool = True) -> Sentiment:
    """Document-level sentiment with an optional per-sentence trace."""
    sentences = split_sentences(text) or [text]
    sentence_scores: list[float] = []
    total = 0.0
    positive = negative = neutral = 0
    positives: Counter = Counter()
    negatives: Counter = Counter()
    for sentence in sentences:
        tokens = words(sentence)
        score, pos_hits, neg_hits = _window_score([token for token in sentence.split()])
        normalised = max(-1.0, min(1.0, score / max(3.0, len(tokens) / 8)))
        sentence_scores.append(round(normalised, 4))
        total += score
        positives.update(pos_hits)
        negatives.update(neg_hits)
        if score > 0.35:
            positive += 1
        elif score < -0.35:
            negative += 1
        else:
            neutral += 1
    count = max(1, len(sentences))
    overall = max(-1.0, min(1.0, total / (count * 2.2)))
    if overall > 0.12:
        label = "positive"
    elif overall < -0.12:
        label = "negative"
    elif positive and negative and min(positive, negative) / max(1, max(positive, negative)) > 0.5:
        label = "mixed"
    else:
        label = "neutral"
    return Sentiment(score=overall, label=label, positive=positive, negative=negative,
                     neutral=neutral, intensity=abs(overall),
                     per_sentence=sentence_scores if per_sentence else [],
                     top_positive=[word for word, _ in positives.most_common(6)],
                     top_negative=[word for word, _ in negatives.most_common(6)])


def polarity(word: str) -> float:
    """Lexicon polarity of a single word (for headline/tone checks)."""
    return POSITIVE.get(word.lower(), NEGATIVE.get(word.lower(), 0.0))


def is_negative(word: str) -> bool:
    return polarity(word) < 0


def tone_words(text: str) -> dict[str, list[str]]:
    """The charged words in a text — used to keep rewrites neutral."""
    tokens = set(words(text))
    return {
        "positive": sorted(token for token in tokens if token in POSITIVE),
        "negative": sorted(token for token in tokens if token in NEGATIVE),
        "intensifiers": sorted(token for token in tokens if token in INTENSIFIERS),
        "contrast": sorted(token for token in tokens if token in CONTRAST),
    }


from collections import Counter  # noqa: E402
