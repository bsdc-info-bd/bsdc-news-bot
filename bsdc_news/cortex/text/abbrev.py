"""Abbreviations, initials and units whose periods must not end a sentence."""

import re

ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "al", "inc", "ltd",
    "co", "corp", "dept", "univ", "assn", "bros", "govt", "sen", "rep", "gov", "gen",
    "col", "capt", "lt", "sgt", "maj", "rev", "hon", "pres", "supt", "det",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
    "ave", "blvd", "rd", "hwy", "apt", "est", "approx", "fig", "figs", "vol", "vols",
    "pp", "para", "ch", "chap", "ed", "eds", "trans", "min", "max", "avg", "esp",
    "eg", "ie", "cf", "viz", "ca", "qtr", "fy", "yo", "mo", "mos", "hr", "hrs",
    "sec", "secs", "ft", "mt", "kg", "lb", "lbs", "oz", "gm", "km", "cm", "mm",
    "mb", "gb", "tb", "kb", "mhz", "ghz", "fps", "dpi", "ceo", "cfo", "cto", "coo",
    "cio", "vp", "svp", "evp", "md", "phd", "mba", "b2b", "b2c", "ai", "ml", "gpu",
    "cpu", "os", "api", "sdk", "app", "apps", "llc", "llp", "plc", "u.s", "u.k",
    "e.u", "a.i", "p.c", "d.c", "i.e", "e.g", "a.m", "p.m", "ph.d", "b.sc", "m.sc",
    "no", "nos", "op", "cit", "ibid", "sq", "misc", "tech", "spec", "specs",
}

_INITIALISM = re.compile(r"\b(?:[A-Za-z]\.){2,}")
_SINGLE_INITIAL = re.compile(r"\b[A-Za-z]\.(?=\s)")
_URLISH = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
_ABBREV_BOUNDARY = re.compile(
    r"\b(?:" + "|".join(sorted({re.escape(a.strip(".")) for a in ABBREVIATIONS if a.strip(".")},
                               key=len, reverse=True)) + r")\.(?=\s|$)",
    re.IGNORECASE,
)


def is_initialism(token: str) -> bool:
    """True for 'U.S.', 'e.g.', 'a.m.'."""
    return bool(_INITIALISM.fullmatch(token.strip()))


def is_abbreviation(token: str) -> bool:
    """True when a trailing period does NOT mean the sentence ended."""
    if not token:
        return False
    token = token.strip()
    if _URLISH.match(token):
        return True
    if is_initialism(token):
        return True
    if len(token) == 2 and token[0].isalpha() and token[1] == ".":
        return True
    return token.strip(".").lower() in ABBREVIATIONS


def protect_abbreviations(text: str, replacer) -> str:
    """Hand every abbreviation/initial to ``replacer`` so splitting can ignore them."""
    text = _INITIALISM.sub(replacer, text)
    text = _SINGLE_INITIAL.sub(replacer, text)
    return _ABBREV_BOUNDARY.sub(replacer, text)
