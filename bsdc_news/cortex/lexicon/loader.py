"""Loader for the bundled lexicon data files.

Everything the engine "knows" beyond morphology lives in `lexicon/data/*.json|txt`
so editors can improve output quality without touching code — and nothing is ever
downloaded at runtime.
"""

import json
import threading
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
_CACHE: dict[str, object] = {}
_LOCK = threading.Lock()


def _load(name: str, default):
    with _LOCK:
        if name in _CACHE:
            return _CACHE[name]
    path = DATA_DIR / name
    if not path.exists():
        return default
    raw = path.read_text(encoding="utf-8")
    value = json.loads(raw) if path.suffix == ".json" else [
        line.strip() for line in raw.splitlines() if line.strip() and not line.startswith("#")]
    with _LOCK:
        _CACHE[name] = value
    return value


def reload() -> None:
    """Drop the cache (used by tests and by `main.py lexicon --reload`)."""
    with _LOCK:
        _CACHE.clear()


def lines(name: str) -> list[str]:
    return list(_load(name, []))


def table(name: str) -> dict:
    return dict(_load(name, {}))


def synonyms() -> dict[str, list[str]]:
    return table("synonyms.json")


def gazetteer_entries() -> dict[str, dict]:
    return table("gazetteer.json")


def power_words() -> set[str]:
    return set(lines("power_words.txt"))


def banned_phrases() -> list[str]:
    return lines("banned_phrases.txt")


def transitions() -> dict[str, list[str]]:
    return table("transitions.json")


def headline_templates() -> list[dict]:
    return list(_load("headline_templates.json", []))


def faq_patterns() -> list[str]:
    return lines("faq_patterns.txt")


def style_rules() -> dict:
    return table("style_guide.json")


def topic_seeds() -> dict[str, list[str]]:
    return table("topic_seeds.json")


def disclosure() -> str:
    text = _load("disclosure.txt", [])
    return " ".join(text) if isinstance(text, list) else str(text)


def place_names() -> set[str]:
    return set(lines("places.txt"))


def tech_terms() -> set[str]:
    return set(lines("tech_terms.txt"))


def anchor_templates() -> list[str]:
    return lines("anchor_templates.txt")
