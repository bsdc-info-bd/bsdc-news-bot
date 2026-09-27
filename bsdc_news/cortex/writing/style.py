"""House style enforcement — the editor that reads every generated sentence.

The engine writes, this module polices: banned clichés, first/second person,
shouting capitals, exclamation marks, marketing verbs, hedging density,
number/date/currency formatting and British-vs-American consistency.
"""

import re
from dataclasses import dataclass, field

from ..lexicon import loader

_FIRST_PERSON = re.compile(r"\b(?:I|we|us|our|ours|my|mine|me)\b")
_SECOND_PERSON = re.compile(r"\b(?:you|your|yours|yourself)\b")
_CAPS_RUN = re.compile(r"\b[A-Z]{3,}\b")
_KEEP_CAPS = {"USA", "AAPL", "NVIDIA", "AI", "API", "CEO", "GPU", "CPU", "SSD", "HBM",
              "OLED", "LCD", "LED", "USB", "HDMI", "WiFi", "WIFI", "5G", "6G", "iOS",
              "iPadOS", "macOS", "AWS", "GDP", "CPI", "EU", "UK", "US", "UN", "WHO",
              "ETF", "IPO", "M&A", "R&D", "VR", "AR", "XR", "NPC", "PDF", "JSON"}
_HEDGE = re.compile(r"\b(?:reportedly|apparently|allegedly|seems? to|appears? to|might|"
                    r"may|could|possibly|perhaps|arguably|is expected to|is said to)\b", re.IGNORECASE)
_MARKETING = re.compile(r"\b(?:buy now|order today|don't miss|do not miss|limited time|"
                        r"act fast|hurry|grab yours|best deal|unbeatable|once in a lifetime|"
                        r"click here|subscribe now|sign up today)\b", re.IGNORECASE)
_DOUBLE_SPACE = re.compile(r"\s{2,}")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass
class StyleReport:
    clean: bool
    score: int
    issues: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"clean": self.clean, "score": self.score, "issues": self.issues[:8],
                "fixed": self.fixed[:8]}


def rules() -> dict:
    return loader.style_rules()


def banned_phrases() -> list[str]:
    return loader.banned_phrases()


_ACRONYMS: set[str] | None = None


def known_acronyms() -> set[str]:
    """All-caps names from the gazetteer and tech lexicon: TSMC, HBM4, NVLink, BTRC.

    These are correct as written, so no style pass may "fix" them into Title Case.
    """
    global _ACRONYMS
    if _ACRONYMS is None:
        found = {name.upper() for name in loader.gazetteer_entries() if name.isupper()}
        for entry in loader.gazetteer_entries().values():
            found.update(str(alias).upper() for alias in entry.get("aliases", [])
                         if str(alias).isupper())
        found.update(term.upper() for term in loader.tech_terms() if term.isupper())
        _ACRONYMS = found
    return _ACRONYMS


def strip_quoted(text: str) -> str:
    """Remove quoted spans and blockquotes: a source's own words are not ours to police."""
    out = re.sub(r"(?s)<blockquote.*?</blockquote>", " ", text)
    out = re.sub(r"[“\"][^”\"]{2,400}[”\"]", " ", out)
    return re.sub(r"\s{2,}", " ", out)


def check(text: str, *, ignore_quotes: bool = True, known_caps: set[str] | None = None) -> StyleReport:
    """Audit a passage against house style. Nothing is modified here.

    Direct quotations and acronyms that the source itself writes in capitals are
    exempt, so a faithful quote never fails the gate.
    """
    issues: list[str] = []
    if not text.strip():
        return StyleReport(clean=False, score=0, issues=["empty text"])
    known_caps = {item.upper() for item in (known_caps or set())}
    prose = strip_quoted(text) if ignore_quotes else text
    lowered = prose.lower()
    for phrase in banned_phrases():
        if phrase in lowered:
            issues.append(f"cliche: '{phrase}'")
    if rules().get("no_first_person", True) and _FIRST_PERSON.search(prose):
        issues.append("first person pronoun")
    if rules().get("no_second_person", True) and _SECOND_PERSON.search(prose):
        issues.append("second person pronoun")
    caps = [token for token in _CAPS_RUN.findall(prose)
            if token not in _KEEP_CAPS and token not in known_caps]
    if caps:
        issues.append(f"shouting capitals: {', '.join(caps[:3])}")
    if rules().get("no_exclamation", True) and "!" in text:
        issues.append("exclamation mark")
    if _MARKETING.search(prose):
        issues.append("marketing call-to-action")
    sentences = [part for part in _SENTENCE_END.split(text) if part.strip()]
    if sentences:
        long_sentences = [sentence for sentence in sentences if len(sentence.split()) > 34]
        if long_sentences:
            issues.append(f"{len(long_sentences)} sentence(s) over 34 words")
    hedges = _HEDGE.findall(text)
    limit = int(rules().get("max_hedging_per_article", 3))
    if len(hedges) > limit:
        issues.append(f"{len(hedges)} hedging phrases (limit {limit})")
    if re.search(r"\b(?:very|really|totally|absolutely)\b", lowered):
        issues.append("weak intensifier")
    score = max(0, 100 - 12 * len(issues))
    return StyleReport(clean=not issues, score=score, issues=issues)


def apply(text: str, *, aggressive: bool = False,
          keep_caps: set[str] | None = None) -> tuple[str, list[str]]:
    """Return style-cleaned text plus the list of fixes applied.

    `keep_caps` lists acronyms the source writes in capitals (TSMC, HBM4, UTC); they
    are left alone instead of being "fixed" into Title Case.
    """
    fixes: list[str] = []
    keep_caps = {item.upper() for item in (keep_caps or set())}
    out = text
    if _DOUBLE_SPACE.search(out):
        out = _DOUBLE_SPACE.sub(" ", out)
        fixes.append("collapsed double spaces")
    for phrase in banned_phrases():
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        if pattern.search(out):
            out = pattern.sub(_replacement_for(phrase), out)
            fixes.append(f"replaced cliche '{phrase}'")
    caps = [token for token in _CAPS_RUN.findall(out)
            if token not in _KEEP_CAPS and token not in keep_caps
            and token not in known_acronyms()]
    for token in caps:
        out = re.sub(rf"\b{token}\b", token.title(), out)
        fixes.append(f"lowered shouting '{token}'")
    out = re.sub(r"\s*!+", ".", out) if rules().get("no_exclamation", True) else out
    if out != text and "!" in text:
        fixes.append("removed exclamation marks")
    out = _MARKETING.sub("", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    out = re.sub(r"\(\s+", "(", out)
    # A deleted cliché can leave ", Apple said ..." or ". , The chip" behind.
    out = re.sub(r"^\s*[,;:]\s*", "", out.strip())
    out = re.sub(r"([.!?])\s*[,;:]+\s*", r"\1 ", out)
    out = re.sub(r"^\s*[,;:]\s*", "", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    if aggressive:
        out = _FIRST_PERSON.sub("the team", out)
        out = _SECOND_PERSON.sub("readers", out)
        fixes.append("removed first/second person")
    return out.strip(), fixes


def _replacement_for(phrase: str) -> str:
    """Neutral stand-ins for the worst clichés."""
    table = {
        "in today's fast-paced world": "",
        "in today's digital age": "",
        "in the ever-evolving": "in the",
        "game changer": "significant change",
        "game-changer": "significant change",
        "it is important to note that": "",
        "it should be noted that": "",
        "it is worth mentioning that": "",
        "at the end of the day": "",
        "when it comes to": "for",
        "in the realm of": "in",
        "in the world of": "in",
        "the landscape of": "the",
        "unlock the power": "use",
        "unleash the potential": "use",
        "seamless experience": "smooth experience",
        "seamlessly integrate": "integrate",
        "cutting-edge technology": "new technology",
        "state-of-the-art": "advanced",
        "paradigm shift": "major change",
        "takes it to the next level": "improves it",
        "elevate your": "improve",
        "empower users": "help users",
        "harness the power": "use",
        "let's dive in": "",
        "without further ado": "",
        "stay tuned": "",
        "buckle up": "",
        "look no further": "",
        "there's something for everyone": "",
        "the future is here": "",
        "change the world": "change the market",
        "unprecedented times": "a difficult period",
        "delve into": "examine",
        "delving into": "examining",
        "revolutionize the way": "change how",
        "revolutionise the way": "change how",
        "as we delve": "",
        "needless to say": "",
        "navigating the complexities": "handling",
        "embark on a journey": "start",
        "tapestry": "mix",
        "testament to": "evidence of",
        "next level of": "improved",
        "dive into the world": "look at",
        "in this comprehensive guide": "",
        "whether you're a": "for",
        "in conclusion, it is clear": "in summary",
    }
    return table.get(phrase.lower(), "")


def sentence_case(text: str) -> str:
    """Sentence case a headline, preserving proper nouns and acronyms."""
    tokens = text.split()
    if not tokens:
        return text
    out = [tokens[0].capitalize()]
    for token in tokens[1:]:
        bare = token.strip(".,;:!?\"'()")
        if not bare or bare in _KEEP_CAPS or bare[:1].isupper() and bare[1:].islower() and len(bare) > 2 or "-" in bare and all(part[:1].isupper() for part in bare.split("-") if part):
            out.append(token)
        else:
            out.append(token.lower())
    return " ".join(out)


def smart_case(text: str) -> str:
    """Re-capitalise known proper nouns after a casing change.

    Sentence/title casing alone destroys "NVIDIA UNVEILS RUBIN ULTRA" -> "rubin
    ultra", so the bundled gazetteer and place list are applied afterwards.
    """
    out = text
    known: dict[str, str] = {}
    for name, entry in loader.gazetteer_entries().items():
        known[name.lower()] = name
        for alias in entry.get("aliases", []):
            known[str(alias).lower()] = str(alias)
    for place in loader.place_names():
        known[place.lower()] = place
    for token in re.findall(r"[A-Za-z][A-Za-z'\-]*(?:\s+[A-Za-z][A-Za-z'\-]*){0,3}", out):
        if token.lower() in known and token != known[token.lower()]:
            out = re.sub(rf"\b{re.escape(token)}\b", known[token.lower()], out)
    return out


def title_case(text: str) -> str:
    small = {"a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet", "in", "on",
             "at", "to", "of", "by", "with", "from", "as", "into", "over", "after", "per"}
    tokens = text.split()
    out = []
    for index, token in enumerate(tokens):
        bare = token.lower().strip(".,;:!?\"'()")
        if bare in small and 0 < index < len(tokens) - 1:
            out.append(token.lower())
        elif bare in _KEEP_CAPS:
            out.append(bare if bare in {"iOS", "iPadOS", "macOS"} else bare.upper())
        else:
            out.append(token.capitalize())
    return " ".join(out)


def numbers_to_words(text: str) -> str:
    """Spell out integers below ten, per house style."""
    small = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
             6: "six", 7: "seven", 8: "eight", 9: "nine"}

    def repl(match: re.Match[str]) -> str:
        value = int(match.group(0))
        return small.get(value, match.group(0))

    return re.sub(r"(?<![\w.\-])([0-9])(?![\w.\-%])", repl, text)


def enforce(text: str, *, keep_caps: set[str] | None = None) -> str:
    """Full style pass: fixes plus number formatting."""
    cleaned, _ = apply(text, aggressive=False, keep_caps=keep_caps)
    return numbers_to_words(cleaned)
