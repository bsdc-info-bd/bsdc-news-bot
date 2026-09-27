"""The bundled knowledge base must exist, load and stay well formed.

These files were once untracked and a workspace reset silently deleted them: the
engine kept running, but with zero gazetteer entries and zero FAQ patterns, so
articles lost their background context and FAQ blocks. Every test here is a tripwire.
"""

import json
import subprocess
from pathlib import Path

import pytest

from bsdc_news.cortex.lexicon import loader

DATA = Path(__file__).resolve().parent.parent / "bsdc_news" / "cortex" / "lexicon" / "data"
REQUIRED = ["gazetteer.json", "places.txt", "tech_terms.txt", "power_words.txt",
            "banned_phrases.txt", "synonyms.json", "transitions.json", "topic_seeds.json",
            "style_guide.json", "headline_templates.json", "faq_patterns.txt",
            "anchor_templates.txt", "disclosure.txt"]


@pytest.fixture(autouse=True)
def _fresh_cache():
    loader.reload()
    yield
    loader.reload()


@pytest.mark.parametrize("name", REQUIRED)
def test_every_data_file_is_present(name):
    assert (DATA / name).exists(), f"{name} is missing — the engine silently degrades without it"


@pytest.mark.parametrize("name", REQUIRED)
def test_every_data_file_is_tracked_by_git(name):
    """An untracked knowledge base is a knowledge base that will be lost."""
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", str(DATA / name)],
                             capture_output=True, text=True)
    assert tracked.returncode == 0, f"{name} is not committed to git"


def test_gazetteer_is_large_enough_to_recognise_entities():
    entries = loader.gazetteer_entries()
    assert len(entries) >= 100
    kinds = {entry["kind"] for entry in entries.values()}
    assert {"ORG", "PERSON"} <= kinds


def test_gazetteer_entries_are_well_formed():
    for name, entry in loader.gazetteer_entries().items():
        assert name and name == name.strip()
        assert entry["kind"] in ("ORG", "PERSON", "PLACE", "PRODUCT", "MISC")
        assert isinstance(entry.get("aliases", []), list)
        assert len(entry.get("summary", "")) >= 20, f"{name} has no usable summary"
    # The extender names the entity and then quotes its summary as background context,
    # so a summary only has to carry real information — six words is the floor.
    usable = [entry for entry in loader.gazetteer_entries().values()
              if len(str(entry.get("summary", "")).split()) >= 6]
    assert len(usable) >= 100, "too few entities carry background the extender can use"


def test_gazetteer_covers_the_home_beat():
    entries = loader.gazetteer_entries()
    surfaces = " ".join(name + " " + " ".join(str(a) for a in entry.get("aliases", []))
                        for name, entry in entries.items()).lower()
    for expected in ("bangladesh bank", "dhaka stock exchange", "btrc", "biman", "bkash",
                     "bgMEA".lower(), "jatiya sangsad", "rooppur"):
        assert expected in surfaces, expected


def test_faq_patterns_all_take_the_subject_slot():
    patterns = loader.faq_patterns()
    assert len(patterns) >= 15
    for pattern in patterns:
        assert "{subject}" in pattern
        assert pattern.format(subject="the rate decision").endswith("?")


def test_headline_templates_only_use_known_slots():
    import re

    known = {"actor", "verb", "object", "detail", "place", "audience", "alternative",
             "claim", "number", "percent", "price", "time"}
    templates = loader.headline_templates()
    assert len(templates) >= 15
    for template in templates:
        slots = set(re.findall(r"\{(\w+)\}", template["pattern"]))
        assert slots and slots <= known, template
        assert "contextual" in template


def test_transitions_cover_every_relation_the_composer_uses():
    transitions = loader.transitions()
    for relation in ("addition", "contrast", "cause", "effect", "sequence", "summary"):
        assert len(transitions.get(relation, [])) >= 4, relation


def test_synonyms_never_map_a_word_to_itself_or_to_a_proper_noun():
    for word, options in loader.synonyms().items():
        assert word == word.lower() and options
        for option in options:
            assert option.lower() != word
            assert not option[:1].isupper()


def test_style_guide_carries_the_rules_the_style_pass_reads():
    rules = loader.style_rules()
    for key in ("no_first_person", "no_second_person", "no_exclamation",
                "max_hedging_per_article", "quote_limit_per_article", "grade_target"):
        assert key in rules


def test_banned_phrases_include_ai_leakage_and_clickbait():
    banned = " ".join(loader.banned_phrases()).lower()
    assert "as an ai language model" in banned
    assert "you won't believe" in banned


def test_places_and_tech_terms_are_substantial():
    assert len(loader.place_names()) >= 120
    assert len(loader.tech_terms()) >= 120
    assert any(" " in term for term in loader.tech_terms())   # compounds are locked too


def test_disclosure_states_that_no_external_ai_was_used():
    text = loader.disclosure().lower()
    assert "no external ai" in text and "automatically" in text


def test_anchor_templates_use_the_title_slot():
    templates = loader.anchor_templates()
    assert templates and all("{title}" in item for item in templates)


def test_every_json_file_is_valid_json():
    for path in DATA.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
