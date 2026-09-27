"""Discourse coherence: does the article read as one connected argument?

Four independent signals, because machine-written copy fails in four different
ways: sentences that do not share subject matter (local), sentences that drift
from the thesis (global), paragraphs that drop the entity chain, and copy that
never returns to its own keyword (focus). All computed offline.
"""

import math
from collections import Counter
from dataclasses import dataclass

from ..text.sentences import split_sentences
from ..text.stopwords import content_words
from ..text.tokenize import words, words_cased


@dataclass
class Coherence:
    local: float              # 0..1 blended neighbour similarity
    global_: float            # 0..1 similarity of each sentence to the centroid
    entity_chain: float       # 0..1 share of neighbouring pairs sharing an entity
    lexical_flow: float       # 0..1 word-level Jaccard between neighbours
    topic_focus: float        # 0..1 share of sentences carrying a topic keyword
    score: int                # 0..100 combined
    weak_points: list[int]    # sentence indexes that break the flow

    def as_dict(self) -> dict:
        return {"local": round(self.local, 4), "global": round(self.global_, 4),
                "entity_chain": round(self.entity_chain, 4),
                "lexical_flow": round(self.lexical_flow, 4),
                "topic_focus": round(self.topic_focus, 4), "score": self.score,
                "weak_points": self.weak_points}


def cosine_counters(a: Counter, b: Counter) -> float:
    """Cosine similarity of two bags of words."""
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    numerator = sum(a[token] * b[token] for token in shared)
    left = math.sqrt(sum(value * value for value in a.values()))
    right = math.sqrt(sum(value * value for value in b.values()))
    return numerator / (left * right) if left and right else 0.0


def jaccard_counters(a: Counter, b: Counter) -> float:
    if not a and not b:
        return 1.0
    union = set(a) | set(b)
    return len(set(a) & set(b)) / len(union) if union else 0.0


def _entities(sentence: str) -> set[str]:
    """Capitalised, meaningful tokens — the entity chain uses case, not lemmas."""
    return {token.strip(".,;:\"'()") for token in words_cased(sentence)
            if token[:1].isupper() and len(token) > 2 and not token.isupper()} | \
           {token for token in words_cased(sentence) if token.isupper() and len(token) > 1}


def analyze(text: str, *, primary_keyword: str = "", topic_terms: list[str] | None = None) -> Coherence:
    sentences = split_sentences(text)
    if len(sentences) < 2:
        return Coherence(local=1.0, global_=1.0, entity_chain=1.0, lexical_flow=1.0,
                         topic_focus=1.0, score=72, weak_points=[])
    bags = [Counter(content_words(words(sentence))) for sentence in sentences]
    entities = [_entities(sentence) for sentence in sentences]
    focus_terms = {term.lower() for term in (topic_terms or [])}
    if primary_keyword:
        focus_terms |= set(primary_keyword.lower().split())
    if not focus_terms:                       # fall back to the document's own top words
        focus_terms = {token for token, _ in Counter(
            token for bag in bags for token in bag).most_common(5)}

    local_pairs: list[float] = []
    chain: list[float] = []
    flow: list[float] = []
    for i in range(len(bags) - 1):
        cosine_value = cosine_counters(bags[i], bags[i + 1])
        shared_entities = 1.0 if entities[i] & entities[i + 1] else 0.0
        jaccard_value = jaccard_counters(bags[i], bags[i + 1])
        local_pairs.append(0.5 * cosine_value + 0.32 * shared_entities + 0.18 * jaccard_value)
        chain.append(shared_entities)
        union = set(bags[i]) | set(bags[i + 1])
        intersection = set(bags[i]) & set(bags[i + 1])
        flow.append(len(intersection) / len(union) if union else 0.0)

    local = sum(local_pairs) / len(local_pairs)
    entity_chain = sum(chain) / len(chain)
    lexical_flow = sum(flow) / len(flow)

    centroid: Counter = Counter()
    for bag in bags:
        centroid.update(bag)
    global_ = sum(cosine_counters(bag, centroid) for bag in bags) / len(bags)

    topic_focus = sum(1 for bag in bags if set(bag) & focus_terms) / len(bags)

    mean_local = local or 1e-6
    weak = [i + 1 for i, value in enumerate(local_pairs) if value < mean_local * 0.4]

    raw = (30 * min(1.0, local * 2.5) + 20 * min(1.0, entity_chain * 1.6)
           + 20 * min(1.0, global_ * 1.3) + 12 * min(1.0, lexical_flow * 4)
           + 18 * topic_focus)
    # Calibrated so ordinary news prose lands near 75 and off-topic text below 35.
    score = min(100.0, raw * 1.7)
    return Coherence(local=local, global_=global_, entity_chain=entity_chain,
                     lexical_flow=lexical_flow, topic_focus=topic_focus,
                     score=round(max(0, min(100, score))), weak_points=weak)


def topic_drift(sentences: list[str]) -> list[float]:
    """Similarity of each sentence to the opening sentence — drift detection."""
    if not sentences:
        return []
    first = Counter(content_words(words(sentences[0])))
    return [round(cosine_counters(first, Counter(content_words(words(sentence)))), 4)
            for sentence in sentences]


def best_insertion_point(existing: list[str], new_sentence: str) -> int:
    """Where a new sentence fits most smoothly — used by the section composer."""
    if not existing:
        return 0
    candidate = Counter(content_words(words(new_sentence)))
    scored = [(cosine_counters(candidate, Counter(content_words(words(sentence)))), index)
              for index, sentence in enumerate(existing)]
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return scored[0][1] + 1 if scored else len(existing)


def transition_needed(previous: str, following: str) -> str:
    """Which discourse relation joins two sentences (drives the transition picker)."""
    previous_bag = set(content_words(words(previous)))
    following_bag = set(content_words(words(following)))
    shared = previous_bag & following_bag
    lowered = following.lower()
    if any(word in lowered for word in ("but", "however", "yet", "still", "instead", "despite")):
        return "contrast"
    if any(word in lowered for word in ("because", "so", "therefore", "as a result", "consequently")):
        return "cause"
    if any(word in lowered for word in ("also", "additionally", "further", "moreover", "separately")):
        return "addition"
    if not shared:
        return "addition"
    if len(following_bag) < len(previous_bag):
        return "summary"
    return "sequence"


def paragraph_breaks(sentences: list[str], *, max_sentences: int = 4) -> list[list[str]]:
    """Group sentences into readable paragraphs at coherence dips."""
    if not sentences:
        return []
    groups: list[list[str]] = [[sentences[0]]]
    for index in range(1, len(sentences)):
        previous = Counter(content_words(words(sentences[index - 1])))
        current = Counter(content_words(words(sentences[index])))
        dip = cosine_counters(previous, current) < 0.06
        if dip or len(groups[-1]) >= max_sentences:
            groups.append([sentences[index]])
        else:
            groups[-1].append(sentences[index])
    return groups
