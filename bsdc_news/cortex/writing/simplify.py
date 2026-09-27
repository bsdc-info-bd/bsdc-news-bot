"""Automatic simplification: make dense copy readable without losing facts.

Targets the three things that kill readability in machine-written news —
over-long sentences, latinate vocabulary and stacked subordinate clauses — while
never touching numbers, names or quotes.
"""

import re

from ..analysis.readability import analyze, hardest_sentences
from ..lexicon import loader
from ..text.sentences import split_sentences

_PLAIN = {
    "utilise": "use", "utilize": "use", "leverage": "use",
    "facilitate": "help", "implement": "add", "implementation": "rollout",
    "subsequent": "later", "subsequently": "later", "prior to": "before",
    "in order to": "to", "commence": "start", "terminate": "end",
    "endeavour": "effort", "endeavor": "effort", "sufficient": "enough",
    "approximately": "about", "numerous": "many", "purchase": "buy",
    "demonstrate": "show", "demonstrates": "shows", "indicate": "show",
    "indicates": "shows", "assistance": "help", "additional": "extra",
    "regarding": "about", "concerning": "about", "currently": "now",
    "previously": "before", "immediately": "at once",
    "component": "part", "components": "parts", "functionality": "features",
    "specifications": "specs", "specification": "spec", "characteristics": "features",
    "methodology": "method", "optimal": "best", "optimise": "improve",
    "optimize": "improve", "significant": "large", "substantial": "large",
    "considerable": "large", "majority": "most", "minority": "few",
    "initiate": "start", "initiated": "started", "modify": "change",
    "modified": "changed", "notify": "tell", "notified": "told",
    "obtain": "get", "obtained": "got", "requirement": "need",
    "requirements": "needs", "retain": "keep", "retained": "kept",
    "select": "pick", "selected": "picked", "transmit": "send",
    "transmitted": "sent", "verify": "check", "verified": "checked",
    "via": "through", "versus": "against", "whilst": "while",
    "amongst": "among", "programme": "program", "analysing": "reviewing",
}
_CONJUNCTION = re.compile(r"\s+(and|but|which|while|although|because|since|so|as|that)\s+", re.IGNORECASE)
_PROTECTED = re.compile(r"(?:\d[\d,\.]*%?|\$[\d,\.]+[mbn]?|[A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*)*)")


def plain_words(text: str) -> tuple[str, list[str]]:
    """Swap latinate vocabulary for plain English."""
    changes: list[str] = []
    out = text
    for fancy, plain in sorted(_PLAIN.items(), key=lambda kv: -len(kv[0])):
        pattern = re.compile(rf"\b{re.escape(fancy)}\b", re.IGNORECASE)
        if not pattern.search(out):
            continue
        replacement = plain.capitalize() if fancy[:1].isupper() else plain
        out = pattern.sub(lambda _m, r=replacement: r, out)
        changes.append(f"{fancy} -> {plain}")
    # Lexicon-driven second pass for anything still long.
    synonyms = loader.synonyms()
    for token in set(re.findall(r"\b[a-z]{10,}\b", out)):
        options = synonyms.get(token)
        if not options:
            continue
        shorter = next((option for option in options if len(option) < len(token) - 2), None)
        if shorter:
            out = re.sub(rf"\b{token}\b", shorter, out)
            changes.append(f"{token} -> {shorter}")
    return out, changes


def split_sentences_text(text: str, *, max_words: int = 26) -> list[str]:
    """Break over-long sentences, but only where the next clause can stand alone.

    Splitting a relative clause ("which is built on...") produces a fragment with
    no subject, so only coordinating conjunctions and semicolons are used, and
    only when what follows starts with a subject.
    """
    subject_start = re.compile(
        r"^(?:the|a|an|this|that|these|those|it|they|he|she|we|you|there|both|each|"
        r"all|some|many|most|several|its|their|his|her|our|my|[A-Z][\w'\-]*)\b")
    out: list[str] = []
    for sentence in split_sentences(text, max_chars=max_words * 12):
        if len(sentence.split()) <= max_words:
            out.append(sentence)
            continue
        pieces: list[str] = []
        current = sentence
        for match in re.finditer(r"(?:;|,\s+(?:and|but|while|whereas)\s+)\s*", current):
            head, tail = current[:match.start()].strip(" ,;"), current[match.end():].strip()
            if len(head.split()) < 5 or len(tail.split()) < 5:
                continue
            if not subject_start.match(tail):
                continue                     # would create a subjectless fragment
            pieces.append(head)
            current = tail
        pieces.append(current.strip(" ,;"))
        for piece in pieces:
            if not piece or len(piece.split()) < 3:
                continue
            piece = piece[0].upper() + piece[1:]
            out.append(piece if piece.endswith((".", "!", "?")) else piece + ".")
    return out


def simplify(text: str, *, target_grade: float = 10.0, max_passes: int = 3) -> tuple[str, dict]:
    """Simplify until the grade level target is met or passes run out."""
    current = text
    report = {"passes": 0, "changes": [], "before": analyze(text), "after": None}
    for attempt in range(max_passes):
        metrics = analyze(current)
        if metrics["average_grade"] and metrics["average_grade"] <= target_grade:
            break
        report["passes"] = attempt + 1
        replaced, changes = plain_words(current)
        report["changes"].extend(changes)
        pieces = split_sentences_text(replaced, max_words=26 if attempt else 30)
        current = " ".join(pieces)
        if current == text and not changes:
            break
    report["after"] = analyze(current)
    return current.strip(), report


def hardest(text: str, *, top: int = 2) -> list[str]:
    return [sentence for sentence, _ in hardest_sentences(text, top=top)]


def protect_facts(text: str) -> tuple[str, dict[str, str]]:
    """Hide numbers and names behind placeholders so simplifying cannot touch them."""
    protected: dict[str, str] = {}

    def stash(match: re.Match[str]) -> str:
        token = f"\x02{len(protected)}\x02"
        protected[token] = match.group(0)
        return token

    return _PROTECTED.sub(stash, text), protected


def restore_facts(text: str, protected: dict[str, str]) -> str:
    for token, original in protected.items():
        text = text.replace(token, original)
    return text
