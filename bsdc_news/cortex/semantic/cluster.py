"""Story clustering: k-means++, agglomerative merging and label extraction.

Several feeds report the same story with different words. Clustering collapses
them into one "story", which lets the pipeline pick the best source, cite the
others as corroboration, and never publish the same event twice.
"""

import random
from collections import Counter

from ..text.stopwords import content_words, is_stopword
from ..text.tokenize import words
from .vectors import SemanticIndex, cosine


def _vectorize(documents: list[str], index: SemanticIndex | None) -> list[list[float]]:
    if index is None:
        index = SemanticIndex(dimensions=32).fit(documents)
    return [index.text_vector(document) or [0.0] * 8 for document in documents]


def kmeans_plus_plus(vectors: list[list[float]], k: int, *, seed: int = 11,
                     iterations: int = 40) -> list[int]:
    """Deterministic k-means++ clustering. Returns a label per document."""
    if not vectors:
        return []
    k = max(1, min(k, len(vectors)))
    rng = random.Random(seed)
    centres = [vectors[rng.randrange(len(vectors))]]
    while len(centres) < k:
        distances = [min((1 - cosine(vector, centre)) for centre in centres) for vector in vectors]
        total = sum(distances) or 1.0
        pick = rng.random() * total
        running = 0.0
        for index, distance in enumerate(distances):
            running += distance
            if running >= pick:
                centres.append(vectors[index])
                break
        else:
            centres.append(vectors[-1])
    labels = [0] * len(vectors)
    for _ in range(iterations):
        changed = False
        for index, vector in enumerate(vectors):
            best = max(range(k), key=lambda c: cosine(vector, centres[c]))
            if best != labels[index]:
                labels[index] = best
                changed = True
        for cluster in range(k):
            members = [vectors[i] for i, label in enumerate(labels) if label == cluster]
            if not members:
                continue
            size = len(members)
            centres[cluster] = [sum(column) / size for column in zip(*members, strict=True)]
        if not changed:
            break
    return labels


def agglomerative(vectors: list[list[float]], *, threshold: float = 0.62) -> list[int]:
    """Average-linkage clustering with a similarity cut — no k required."""
    clusters = [[index] for index in range(len(vectors))]
    while len(clusters) > 1:
        best_pair, best_score = None, threshold
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                score = _average_link(vectors, clusters[i], clusters[j])
                if score > best_score:
                    best_pair, best_score = (i, j), score
        if best_pair is None:
            break
        i, j = best_pair
        clusters[i] = clusters[i] + clusters[j]
        del clusters[j]
    labels = [0] * len(vectors)
    for label, cluster in enumerate(clusters):
        for index in cluster:
            labels[index] = label
    return labels


def _average_link(vectors: list[list[float]], left: list[int], right: list[int]) -> float:
    total = 0.0
    for i in left:
        for j in right:
            total += cosine(vectors[i], vectors[j])
    return total / (len(left) * len(right))


def cluster_documents(documents: list[str], *, method: str = "agglomerative",
                      k: int = 4, threshold: float = 0.62,
                      index: SemanticIndex | None = None) -> list[int]:
    """Cluster raw documents by meaning."""
    if len(documents) < 2:
        return [0] * len(documents)
    vectors = _vectorize(documents, index)
    if method == "kmeans":
        return kmeans_plus_plus(vectors, k)
    return agglomerative(vectors, threshold=threshold)


def cluster_label(documents: list[str], members: list[int], *, top: int = 3) -> str:
    """Title-case label for a cluster: its most distinctive frequent phrase."""
    text = " ".join(documents[index] for index in members)
    counts = Counter(content_words(words(text)))
    background = Counter(content_words(words(" ".join(documents))))
    scored = []
    for token, count in counts.items():
        if count < 2 or is_stopword(token) or len(token) < 3:
            continue
        distinctiveness = count / max(1, background[token])
        scored.append((token, count * distinctiveness))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    label = " ".join(token for token, _ in scored[:top])
    return label.title() if label else "General News"


def cluster_sizes(labels: list[int]) -> dict[int, int]:
    return dict(Counter(labels))


def largest_cluster(labels: list[int]) -> int:
    sizes = cluster_sizes(labels)
    return max(sizes, key=lambda key: sizes[key]) if sizes else -1


def corroboration(documents: list[str], index_in_cluster: int, labels: list[int]) -> list[int]:
    """Other documents reporting the same story — used for 'others also reported'."""
    label = labels[index_in_cluster]
    return [i for i, other in enumerate(labels) if other == label and i != index_in_cluster]
