"""Rule-based lemmatiser with an irregular-form table.

Unlike stemming, lemmas are real words, so they are what the writer, the SEO
keyword planner and the headline generator work with.
"""

import re

IRREGULAR = {
    "children": "child", "men": "man", "women": "woman", "people": "person",
    "feet": "foot", "teeth": "tooth", "mice": "mouse", "geese": "goose",
    "data": "datum", "media": "medium", "criteria": "criterion", "phenomena": "phenomenon",
    "analyses": "analysis", "indices": "index", "matrices": "matrix", "vertices": "vertex",
    "appendices": "appendix", "cacti": "cactus", "alumni": "alumnus", "fungi": "fungus",
    "nuclei": "nucleus", "syllabi": "syllabus", "foci": "focus", "genera": "genus",
    "went": "go", "gone": "go", "was": "be", "were": "be", "been": "be", "am": "be",
    "is": "be", "are": "be", "had": "have", "has": "have", "did": "do", "does": "do",
    "said": "say", "made": "make", "took": "take", "taken": "take", "came": "come",
    "saw": "see", "seen": "see", "knew": "know", "known": "know", "thought": "think",
    "bought": "buy", "brought": "bring", "built": "build", "sent": "send", "spent": "spend",
    "sold": "sell", "told": "tell", "found": "find", "kept": "keep", "left": "leave",
    "lost": "lose", "meant": "mean", "paid": "pay", "read": "read", "ran": "run",
    "began": "begin", "begun": "begin", "grew": "grow", "grown": "grow", "held": "hold",
    "led": "lead", "met": "meet", "rode": "ride", "rose": "rise", "sat": "sit",
    "spoke": "speak", "spoken": "speak", "stood": "stand", "understood": "understand",
    "wrote": "write", "written": "write", "drove": "drive", "driven": "drive",
    "ate": "eat", "eaten": "eat", "fell": "fall", "fallen": "fall", "gave": "give",
    "given": "give", "got": "get", "hidden": "hide", "laid": "lay", "learnt": "learn",
    "best": "good", "better": "good", "worse": "bad", "worst": "bad", "more": "many",
    "most": "many", "less": "little", "least": "little", "further": "far",
    "lives": "life", "knives": "knife", "wives": "wife", "wolves": "wolf",
    "halves": "half", "shelves": "shelf", "leaves": "leaf", "loaves": "loaf",
    "thieves": "thief", "selves": "self", "elves": "elf", "calves": "calf",
    "news": "news", "series": "series", "species": "species", "electronics": "electronics",
}

_SUFFIX_RULES = (
    ("ies", "y", 4), ("sses", "ss", 0), ("ves", "f", 4), ("oes", "o", 4),
    ("ches", "ch", 0), ("shes", "sh", 0), ("xes", "x", 0), ("zes", "z", 0),
    ("ations", "ation", 0), ("ments", "ment", 0), ("nesses", "ness", 0),
    ("ities", "ity", 0), ("ives", "ive", 0), ("ers", "er", 3), ("ests", "est", 0),
    ("ings", "ing", 0),
)

_VERB_ENDINGS = ("ate", "ify", "ise", "ize", "ect", "end", "eve", "ing", "ed")


def lemma(word: str) -> str:
    """Best-effort singular/base form of a lower-case word."""
    word = re.sub(r"[^a-z'\-]", "", word.lower())
    if not word or word in {"news", "electronics", "series", "species"}:
        return word
    if word in IRREGULAR:
        return IRREGULAR[word]
    for suffix, replacement, min_len in _SUFFIX_RULES:
        if word.endswith(suffix) and len(word) > min_len + len(suffix) - 1:
            return word[: -len(suffix)] + replacement
    if word.endswith("ses") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is", "as")) and len(word) > 3:
        return word[:-1]
    if word.endswith("ing") and len(word) > 5:
        stem = word[:-3]
        if stem.endswith(("bl", "iz", "at")):
            return stem + "e"
        if re.search(r"([bcdfglmnprstvz])\1$", stem):
            return stem[:-1]
        return stem if len(stem) > 2 else stem + "e"
    if word.endswith("ed") and len(word) > 4:
        stem = word[:-2]
        if stem.endswith(("at", "iz", "bl")):
            return stem + "e"
        if re.search(r"([bcdfglmnprstvz])\1$", stem):
            return stem[:-1]
        if any(stem.endswith(ending) for ending in _VERB_ENDINGS) or len(stem) > 3:
            return stem
    if word.endswith(("ly",)) and len(word) > 4:
        return word[:-2]
    return word


def lemma_all(tokens: list[str]) -> list[str]:
    return [lemma(token) for token in tokens]


def lemmatized_set(tokens: list[str]) -> set[str]:
    return {lemma(token) for token in tokens}


def pluralize(word: str) -> str:
    """Regular English plural — used for label and heading generation."""
    if not word:
        return word
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("f", "fe")):
        return re.sub(r"fe?$", "ves", word)
    return word + "s"


def is_lemma_form(word: str) -> bool:
    return lemma(word) == word.lower()
