"""Latent Dirichlet Allocation with collapsed Gibbs sampling — pure Python.

Gives the pipeline a real topic model: it labels stories, tracks topic heat over
time, checks topical authority (does the blog cover this theme?) and provides
LSI keyword candidates that TF-IDF alone cannot find.
"""

import random
from collections import Counter, defaultdict

from ..text.stopwords import content_words
from ..text.tokenize import words


class LDA:
    """Collapsed Gibbs sampler with a fixed seed, so runs are reproducible."""

    def __init__(self, topics: int = 8, *, alpha: float = 0.1, beta: float = 0.01,
                 seed: int = 17) -> None:
        self.topics = topics
        self.alpha = alpha
        self.beta = beta
        self.seed = seed
        self.vocabulary: list[str] = []
        self.word_index: dict[str, int] = {}
        self.word_topic: dict[int, Counter] = defaultdict(Counter)
        self.doc_topic: dict[int, Counter] = defaultdict(Counter)
        self.topic_totals: Counter = Counter()
        self.assignments: list[list[int]] = []
        self.documents: list[list[int]] = []
        self.iterations = 0

    def _tokenize(self, documents: list[str]) -> list[list[int]]:
        self.vocabulary = sorted({token for document in documents
                                  for token in content_words(words(document))})
        self.word_index = {token: index for index, token in enumerate(self.vocabulary)}
        return [[self.word_index[token] for token in content_words(words(document))]
                for document in documents]

    def fit(self, documents: list[str], *, iterations: int = 60) -> "LDA":
        self.documents = self._tokenize(documents)
        if not self.vocabulary:
            return self
        rng = random.Random(self.seed)
        self.assignments = []
        for doc_index, tokens in enumerate(self.documents):
            row = []
            for token in tokens:
                topic = rng.randrange(self.topics)
                row.append(topic)
                self.word_topic[token][topic] += 1
                self.doc_topic[doc_index][topic] += 1
                self.topic_totals[topic] += 1
            self.assignments.append(row)
        vocabulary_size = len(self.vocabulary)
        for _ in range(iterations):
            self.iterations += 1
            for doc_index, tokens in enumerate(self.documents):
                for position, token in enumerate(tokens):
                    old = self.assignments[doc_index][position]
                    self.word_topic[token][old] -= 1
                    self.doc_topic[doc_index][old] -= 1
                    self.topic_totals[old] -= 1
                    weights = []
                    for topic in range(self.topics):
                        numerator = (self.word_topic[token][topic] + self.beta) * \
                                    (self.doc_topic[doc_index][topic] + self.alpha)
                        denominator = self.topic_totals[topic] + vocabulary_size * self.beta
                        weights.append(numerator / denominator)
                    total = sum(weights) or 1.0
                    pick = rng.random() * total
                    running = 0.0
                    chosen = self.topics - 1
                    for topic, weight in enumerate(weights):
                        running += weight
                        if running >= pick:
                            chosen = topic
                            break
                    self.assignments[doc_index][position] = chosen
                    self.word_topic[token][chosen] += 1
                    self.doc_topic[doc_index][chosen] += 1
                    self.topic_totals[chosen] += 1
        return self

    def topic_words(self, topic: int, *, top: int = 10) -> list[tuple[str, float]]:
        scored = [(self.vocabulary[word], count / max(1, self.topic_totals[topic]))
                  for word, counts in self.word_topic.items() if (count := counts.get(topic, 0))]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [(word, round(score, 5)) for word, score in scored[:top]]

    def topic_label(self, topic: int, *, top: int = 3) -> str:
        label = " ".join(word for word, _ in self.topic_words(topic, top=top))
        return label.title() if label else f"Topic {topic}"

    def document_distribution(self, doc_index: int) -> dict[int, float]:
        total = sum(self.doc_topic[doc_index].values()) or 1
        return {topic: round(count / total, 4) for topic, count in self.doc_topic[doc_index].items()}

    def document_topic(self, doc_index: int) -> int:
        counts = self.doc_topic[doc_index]
        return max(counts, key=lambda topic: counts[topic]) if counts else 0

    def classify(self, text: str) -> tuple[int, float]:
        """Assign unseen text to the nearest topic by word-topic distribution."""
        tokens = [self.word_index[token] for token in content_words(words(text))
                  if token in self.word_index]
        if not tokens:
            return 0, 0.0
        scores: dict[int, float] = defaultdict(float)
        for token in tokens:
            total = max(1, sum(self.word_topic[token].values()))
            for topic, count in self.word_topic[token].items():
                scores[topic] += count / total
        if not scores:
            return 0, 0.0
        best = max(scores, key=lambda topic: scores[topic])
        grand = sum(scores.values()) or 1.0
        return best, round(scores[best] / grand, 4)

    def coherence(self, topic: int, *, top: int = 8) -> float:
        """Average normalised pointwise mutual information between top words."""
        top_words = [word for word, _ in self.topic_words(topic, top=top)]
        if len(top_words) < 2:
            return 0.0
        total = 0.0
        pairs = 0
        for i, first in enumerate(top_words):
            for second in top_words[i + 1:]:
                first_index = self.word_index.get(first)
                second_index = self.word_index.get(second)
                if first_index is None or second_index is None:
                    continue
                together = sum(1 for document in self.documents
                               if first_index in document and second_index in document)
                if not together:
                    continue
                left = sum(1 for document in self.documents if first_index in document)
                right = sum(1 for document in self.documents if second_index in document)
                all_docs = max(1, len(self.documents))
                total += _pmi(together, left, right, all_docs)
                pairs += 1
        return round(total / pairs, 4) if pairs else 0.0

    def sizes(self) -> dict[int, int]:
        return dict(self.topic_totals)


def _pmi(together: int, left: int, right: int, total: int) -> float:
    import math

    joint = together / total
    product = (left / total) * (right / total)
    if joint <= 0 or product <= 0:
        return 0.0
    return math.log(joint / product)


def topics_of(documents: list[str], *, topics: int = 6, iterations: int = 40) -> LDA:
    return LDA(topics=topics).fit(documents, iterations=iterations)


def topic_keywords(model: LDA, *, top: int = 12) -> dict[int, list[str]]:
    return {topic: [word for word, _ in model.topic_words(topic, top=top)]
            for topic in range(model.topics)}
