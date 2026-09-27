"""The keyword planner: six signals fused into one ranked keyword set.

Signals
-------
1. TF-IDF salience with positional weighting (`analysis.freq`)
2. RAKE keyphrases (`analysis.rake`)
3. TextRank word centrality (`analysis.textrank`)
4. Noun-phrase frequency (`text.chunks`)
5. Named-entity boost (`analysis.entities`)
6. Headline/title overlap — the words the source itself treats as the topic

The result is a structured set (primary, secondary, LSI, long-tail) plus a search
intent classification, which the SEO layer turns into titles, slugs, headings,
schema and internal-link anchors.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from ..text import pos
from ..text.chunks import phrases as chunk_phrases
from ..text.lemma import lemma
from ..text.sentences import split_sentences
from ..text.stopwords import GENERIC_TECH, content_words, is_stopword
from ..text.tokenize import bigrams, words
from .freq import salience
from .rake import rake
from .textrank import rank_words

INTENT_CUES = {
    "transactional": ("buy", "price", "prices", "deal", "deals", "discount", "offer",
                      "sale", "order", "preorder", "pre-order", "available now", "shipping",
                      "cost", "costs", "subscription", "plan", "pricing", "coupon"),
    "informational": ("how", "why", "what", "guide", "explained", "explains", "learn",
                      "tips", "tutorial", "meaning", "definition", "vs", "versus",
                      "comparison", "review", "overview", "analysis"),
    "navigational": ("login", "sign in", "app download", "official site", "website",
                     "portal", "dashboard", "support page"),
    "news": ("launch", "launches", "announced", "announces", "unveils", "unveiled",
             "reveals", "released", "rolls out", "confirmed", "reports", "says",
             "breaking", "update", "leak", "leaked", "rumor", "rumour"),
}


@dataclass
class KeywordSet:
    primary: str = ""
    secondary: list[str] = field(default_factory=list)
    lsi: list[str] = field(default_factory=list)
    long_tail: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    intent: str = "news"
    scores: dict[str, float] = field(default_factory=dict)
    stemmed: dict[str, str] = field(default_factory=dict)

    def all_terms(self) -> list[str]:
        out = [self.primary] if self.primary else []
        out.extend(self.secondary)
        out.extend(self.lsi)
        return [term for term in out if term]

    def as_dict(self) -> dict:
        return {"primary": self.primary, "secondary": self.secondary, "lsi": self.lsi,
                "long_tail": self.long_tail, "entities": self.entities,
                "numbers": self.numbers, "intent": self.intent}


_NON_WORD = re.compile(r"^[\d\W]+$")
# Nouns that are grammatically fine but never searched for: calendar words, vague
# time spans and newsroom furniture. "Monday" must not become a primary keyword.
NON_KEYWORD = frozenset([
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "today", "tomorrow",
    "yesterday", "tonight", "week", "weeks", "month", "months", "year", "years",
    "quarter", "quarters", "decade", "century", "morning", "evening", "afternoon",
    "night", "weekend", "thing", "things", "stuff", "lot", "lots", "bit", "bits",
    "way", "ways", "part", "parts", "side", "sides", "point", "points", "time",
    "times", "day", "days", "hour", "hours", "minute", "minutes", "second",
    "seconds", "people", "person", "man", "woman", "men", "women", " guy", "area",
    "areas", "place", "places", "country", "countries", "world", "life", "lives",
    "news", "story", "stories", "report", "reports", "article", "articles", "post",
    "posts", "blog", "page", "pages", "site", "sites", "version", "versions",
    "example", "examples", "case", "cases", "kind", "kinds", "type", "types",
    "level", "levels", "amount", "amounts", "number", "numbers", "total", "totals",
    "end", "ends", "start", "starts", "beginning", "middle", "top", "bottom",
    "left", "right", "front", "back", "inside", "outside", "future", "past",
    "present", "moment", "period", "phase", "stage", "step", "steps", "issue",
    "issues", "problem", "problems", "question", "questions", "answer", "answers",
    "fact", "facts", "detail", "details", "information", "data", "content",
])
_PUNCT_EDGE = '.,;:!?\"'"'"'()'


def topical(token: str) -> bool:
    """Could this token ever be a search keyword?

    Years, money, percentages and bare punctuation score highly on frequency but are
    useless (and embarrassing) as a primary keyword, so they are excluded up front.
    """
    cleaned = token.strip(_PUNCT_EDGE).lower()
    if len(cleaned) < 3 or _NON_WORD.match(cleaned):
        return False
    if sum(ch.isdigit() for ch in cleaned) >= max(1, len(cleaned) // 2):
        return False
    if sum(ch.isalpha() for ch in cleaned) < 3:
        return False
    if cleaned in NON_KEYWORD:
        return False
    if "'" in cleaned or "\u2019" in cleaned:
        return False                       # "bangladesh's central bank" is not a query
    return not is_stopword(cleaned) and cleaned not in GENERIC_TECH


def _normalise(phrase: str) -> str:
    return re.sub(r"\s+", " ", phrase.strip().lower().strip(".,;:!?\"'()[]"))


def _dedupe(ranked: list[tuple[str, float]], *, keep: int) -> list[tuple[str, float]]:
    """Keep the best form of each concept: prefer longer phrases, drop contained ones."""
    out: list[tuple[str, float]] = []
    for phrase, score in ranked:
        if any(phrase != other and phrase in other for other, _ in out):
            continue
        out = [(other, other_score) for other, other_score in out if not (other != phrase and other in phrase)]
        out.append((phrase, score))
        out.sort(key=lambda pair: -pair[1])
        if len(out) >= keep * 3:
            out = out[:keep * 3]
    return out[:keep]


# A keyphrase that runs from a name straight into a verb is a fragment of a sentence,
# not something anyone searches for.
_VERB_BREAK = frozenset(["said", "says", "saids", "told", "reported", "announces", "announced", "announce", "added", "adds", "forecast", "forecasts", "predicted", "predicts", "expects", "expected", "warns", "warned", "warneds", "cuts", "cut", "raises", "raised", "lowered", "lowers", "will", "has", "have", "had", "is", "are", "was", "were", "be", "been", "may", "might", "can", "could", "would", "should", "plans", "planned", "sees", "saw", "seeks", "sought", "denies", "denied", "confirms", "confirmed", "reveals", "revealed", "according"])


def detect_intent(text: str, headline: str = "") -> str:
    """Classify search intent from cue words in the headline and lede."""
    haystack = f"{headline} {text[:600]}".lower()
    scores = {intent: sum(haystack.count(cue) for cue in cues) for intent, cues in INTENT_CUES.items()}
    scores["news"] += 2 * len(re.findall(r"\b(?:said|says|announced|announces)\b", haystack))
    best = max(scores, key=lambda key: scores[key])
    return best if scores[best] > 0 else "news"


def plan(text: str, *, headline: str = "", entity_names: list[str] | None = None,
         trends: list[str] | None = None, numeric_phrases: list[str] | None = None,
         top: int = 12) -> KeywordSet:
    """Build the keyword set for one article."""
    entity_names = entity_names or []
    trends = [trend.lower() for trend in (trends or [])]
    numeric_phrases = numeric_phrases or []
    tokens = words(text)
    headline_words = words(headline)
    headline_tokens = set(headline_words)
    if not tokens:
        return KeywordSet(intent=detect_intent(text, headline))

    # 1. salience (TF-IDF + position + lead boost)
    base = salience(text, top=40)
    # A verb can score highly on frequency ("unveiled", "said") but nobody searches
    # for it, so only tokens the tagger sees as nouns may become keywords.
    noun_forms = {item.token.lower() for item in pos.tag_text(text)
                  if item.tag.startswith("NN")}
    # 2. RAKE keyphrases
    rake_scores = {phrase: score for phrase, score in rake(text, top=25)}
    rake_peak = max(rake_scores.values()) if rake_scores else 1.0
    # 3. TextRank centrality
    textrank_scores = {token: score for token, score in rank_words(text, top=30)}
    textrank_peak = max(textrank_scores.values()) if textrank_scores else 1.0
    # 4. noun phrases
    phrase_counts = Counter(_normalise(phrase) for phrase in chunk_phrases(text))
    # 5/6. boosts
    entities = {_normalise(name) for name in entity_names}
    # Half of a multi-word name is not a keyword: "San" from "San Jose" scores well on
    # frequency and positional weight but nobody searches for it.
    fragments = {part for name in entity_names if len(name.split()) > 1
                 for part in name.lower().split()} - {name.lower() for name in entity_names}
    combined: dict[str, float] = {}

    # Seed every named entity as a candidate, even when the chunker missed it.
    lowered_text = text.lower()
    text_length = max(1, len(lowered_text))
    for name in entity_names:
        key = _normalise(name)
        if not key or len(key) < 3:
            continue
        mentions = lowered_text.count(name.lower())
        value = 1.15 + 0.4 * min(4, mentions) + 0.45 * len(key.split())
        if any(part in headline_tokens for part in key.split()):
            value += 1.0                       # the source calls this the subject
        first = lowered_text.find(name.lower())
        if 0 <= first < text_length * 0.2:
            value += 0.6                       # named in the opening: it is the story
        combined[key] = round(max(combined.get(key, 0.0), value), 4)

    salience_peak = max(base.values()) if base else 1.0
    for token, score in base.items():
        if not topical(token) or token.strip(_PUNCT_EDGE).lower() not in noun_forms:
            continue
        if token.strip(_PUNCT_EDGE).lower() in fragments:
            continue
        # Salience is unbounded TF-IDF, so a rare word ("dies", "reticle") would
        # otherwise swamp every other signal; the peak normalisation keeps the six
        # signals on one comparable scale.
        value = 2.0 * (score / salience_peak)
        value += 1.2 * (textrank_scores.get(token, 0.0) / textrank_peak)
        value += 0.9 * (rake_scores.get(token, 0.0) / rake_peak)
        value += 0.8 * min(1.0, phrase_counts.get(token, 0) / 3)
        if token in headline_tokens:
            value += 1.1
        if token in entities:
            value += 1.4
        if token in trends:
            value += 1.0
        combined[token] = round(value, 4)

    for phrase, count in phrase_counts.items():
        parts = phrase.split()
        if len(parts) < 2 or is_stopword(phrase):
            continue
        if not all(topical(part) for part in parts):
            continue
        if not any(part in noun_forms for part in parts):
            continue
        value = 1.5 * min(1.0, count / 2) + 0.35 * len(parts)
        value += 0.9 * (rake_scores.get(phrase, 0.0) / rake_peak)
        value += sum(0.35 * (textrank_scores.get(part, 0.0) / textrank_peak) for part in parts)
        if any(part in headline_tokens for part in parts):
            value += 1.0
        if phrase in entities:
            value += 1.6
        if phrase in trends or any(part in trends for part in parts):
            value += 1.1
        # max(), not +=: an entity-seeded phrase would otherwise be scored twice and
        # a passing mention ("Meridian Research") would outrank the subject.
        if phrase in entities:
            value += 1.6
        combined[phrase] = round(max(combined.get(phrase, 0.0), value), 4)

    for phrase in rake_scores:
        parts = phrase.split()
        if len(parts) < 2 or phrase in combined:
            continue
        if not all(topical(part) for part in parts):
            continue                       # "bangladesh bank abdul hafez said" is not a keyword
        if parts[1] in _VERB_BREAK or parts[-1] in _VERB_BREAK:
            continue                       # "bangladesh forecast growth" is a name + a verb
        combined[phrase] = round(0.8 * (rake_scores[phrase] / rake_peak), 4)

    ranked = _dedupe(sorted(combined.items(), key=lambda kv: (-kv[1], kv[0])), keep=top * 2)
    # An editor picks the focus keyword from the headline and the first sentence, not
    # from the rarest phrase in the body. A passing mention ("Meridian Research") can
    # outscore the subject on TF-IDF alone, so anchor the ranking to the headline/lead.
    lead = split_sentences(text)[0] if split_sentences(text) else ""
    lead_tokens = set(words(lead))
    scored = sorted(((phrase, round(_anchor(phrase, score, headline_tokens, lead_tokens,
                                            lowered_text, entities, text_length), 4))
                     for phrase, score in ranked), key=lambda kv: (-kv[1], kv[0]))
    scored = _truncate_to_entity(scored, entities)
    scored = _prefer_phrase(scored, entity_phrases=entities)
    # An editor picks the focus keyword from the headline the source itself wrote.
    # A rare body phrase ("National Payment Switch", "Policy Research Institute") can
    # outscore the actual subject on TF-IDF, so headline-anchored candidates are moved
    # to the front *before* the list is cut down to `top` — otherwise the subject never
    # survives the cut and the focus keyword ends up being a passing mention.
    if headline_tokens:
        anchored = [item for item in scored
                    if any(part in headline_tokens for part in item[0].split())]
        if anchored:
            anchored.sort(key=lambda kv: (_headline_position(kv[0], headline_words), -kv[1]))
            rest = [item for item in scored if item not in anchored]
            scored = anchored + rest
    ranked = _drop_verb_fragments(scored[:top])
    primary = ranked[0][0] if ranked else ""
    secondary = [phrase for phrase, _ in ranked[1:5]]
    lsi = [phrase for phrase, _ in ranked[5:top]]

    long_tail = [phrase for phrase, _ in ranked if len(phrase.split()) >= 3][:5]
    if not long_tail:                      # synthesise one from primary + a modifier
        modifiers = [cue for cue in ("price", "release date", "specs", "features", "review")
                     if cue not in primary]
        long_tail = [f"{primary} {modifiers[0]}"] if primary and modifiers else []

    lemma_map = {phrase: lemma(phrase.split()[0]) for phrase, _ in ranked if phrase}
    return KeywordSet(primary=primary, secondary=secondary, lsi=lsi, long_tail=long_tail,
                      entities=[name for name in entity_names if _normalise(name) in combined][:8],
                      numbers=[_normalise(phrase) for phrase in numeric_phrases][:8],
                      intent=detect_intent(text, headline),
                      scores=dict(ranked), stemmed=lemma_map)


def _drop_verb_fragments(ranked: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Remove keyphrases that are really a name followed by a verb.

    RAKE happily returns "bangladesh forecast growth" from "...Institute of Bangladesh
    forecast growth of 5.8 percent...". Nobody searches for that, and it wastes one of
    the four secondary slots the meta description and headings are built from.
    """
    kept = [item for item in ranked
            if not any(token in _VERB_BREAK for token in item[0].split()[1:])]
    return kept or ranked


def _headline_position(phrase: str, headline_words: list[str]) -> int:
    """Where the phrase first appears in the headline — the subject comes first."""
    parts = phrase.split()
    for index, word in enumerate(headline_words):
        if word in parts:
            return index
    return len(headline_words)


def _truncate_to_entity(ranked: list[tuple[str, float]], entities: set[str]) -> list[tuple[str, float]]:
    """Cut a keyphrase back to the entity it starts with.

    The chunker happily returns "bangladesh bank abdul hafez" because the words are
    adjacent and capitalised. The keyword is the organisation, not the organisation
    plus the governor who happens to follow it in the sentence.
    """
    if not entities:
        return ranked
    names = sorted((entity for entity in entities if " " in entity), key=len, reverse=True)
    out: list[tuple[str, float]] = []
    merged: dict[str, float] = {}
    for phrase, score in ranked:
        replacement = phrase
        for name in names:
            if phrase != name and phrase.startswith(f"{name} "):
                replacement = name
                break
        if replacement != phrase:
            merged[replacement] = max(merged.get(replacement, 0.0), score)
            continue
        merged[phrase] = max(merged.get(phrase, 0.0), score)
    for phrase, _score in ranked:
        if phrase in merged:
            out.append((phrase, merged.pop(phrase)))
    out.extend((phrase, score) for phrase, score in merged.items())
    out.sort(key=lambda item: (-item[1], item[0]))
    return out


def _anchor(phrase: str, score: float, headline_tokens: set[str], lead_tokens: set[str],
            lowered_text: str, entities: set[str], text_length: int) -> float:
    """Boost a candidate that the source itself treats as the subject.

    Two phrases can tie on evidence ("rubin ultra accelerator" and "the equivalent
    rubin rack"), so the tie-break is how a search phrase actually looks: it starts
    with the named thing, appears early, and is not led by a loose adjective.
    """
    parts = phrase.split()
    boost = 0.0
    if headline_tokens and any(part in headline_tokens for part in parts):
        boost += 2.0
    if lead_tokens and any(part in lead_tokens for part in parts):
        boost += 1.0
    boost += 0.35 * min(4, lowered_text.count(phrase))
    if phrase in entities:
        boost += 1.4
    elif any(phrase.startswith(f"{entity} ") for entity in entities):
        boost += 1.2                       # the product name leads the phrase
    first = lowered_text.find(phrase)
    if text_length and 0 <= first < text_length * 0.25:
        boost += 0.6
    if parts and pos.tag_token(parts[0]).startswith("JJ"):
        boost -= 1.5                       # "equivalent rubin rack" is not a query
    return score + boost


def _prefer_phrase(ranked: list[tuple[str, float]], *, entity_phrases: set[str] | None = None,
                   tolerance: float = 0.80, entity_tolerance: float = 0.55) -> list[tuple[str, float]]:
    """Promote a multi-word phrase — above all a named entity — to primary.

    "rubin ultra" is a far better primary keyword than "chip" or a stray noun like
    "monday", and search traffic is won by the phrases people actually type.
    """
    if not ranked:
        return ranked
    if len(ranked[0][0].split()) > 1:
        # The winner is already a keyphrase; promoting some other entity phrase here
        # would replace the subject with a passing mention.
        return ranked
    entity_phrases = entity_phrases or set()
    top_score = ranked[0][1]
    for phrase, phrase_score in ranked:
        if len(phrase.split()) < 2 or phrase not in entity_phrases:
            continue
        if phrase_score >= top_score * entity_tolerance:
            return [(phrase, phrase_score)] + [item for item in ranked if item[0] != phrase]
    if len(ranked[0][0].split()) > 1:
        return ranked
    top_term = ranked[0][0]
    for phrase, phrase_score in ranked[1:]:
        parts = phrase.split()
        if len(parts) < 2 or phrase_score < top_score * tolerance:
            continue
        if top_term in parts:
            return [(phrase, phrase_score)] + [item for item in ranked if item[0] != phrase]
    return ranked


def relatedness(source: str, candidate: str) -> float:
    """Shared-keyword overlap between two texts — used for internal linking."""
    a = set(content_words(words(source)))
    b = set(content_words(words(candidate)))
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def coverage(text: str, keyword_set: KeywordSet) -> float:
    """How well the finished copy actually covers its own keyword plan (0..1)."""
    tokens = words(text)
    joined = " ".join(tokens)
    if not tokens:
        return 0.0
    terms = keyword_set.all_terms() or [keyword_set.primary]
    hits = 0
    for term in terms:
        if " " in term:
            hits += 1 if term in joined else 0
        else:
            hits += 1 if term in tokens else 0
    return round(hits / max(1, len(terms)), 3)


def phrase_variants(phrase: str) -> list[str]:
    """Surface variants of a keyphrase for natural repetition in copy."""
    out = [phrase]
    tokens = phrase.split()
    if len(tokens) > 1:
        out.append(" ".join(lemma(token) for token in tokens))
        out.append(tokens[-1])
    singular = lemma(phrase) if len(tokens) == 1 else phrase
    if singular != phrase:
        out.append(singular)
    return list(dict.fromkeys(variant for variant in out if variant))


def bigram_candidates(text: str, *, top: int = 10) -> list[tuple[str, int]]:
    """Frequent bigrams — cheap long-tail discovery."""
    counts = Counter(bigram for bigram in bigrams(content_words(words(text)))
                     if not is_stopword(bigram.split()[0]))
    return counts.most_common(top)


def sentences_mentioning(text: str, term: str) -> list[str]:
    """Sentences that contain a keyword — used for FAQ and internal-link context."""
    lowered = term.lower()
    return [sentence for sentence in split_sentences(text) if lowered in sentence.lower()]
