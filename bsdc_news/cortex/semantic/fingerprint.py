"""Locality-sensitive hashing: SimHash, MinHash and band-based LSH.

SimHash answers "is this article substantially the same as one we published?" in
O(1) with a 64-bit integer; MinHash + banding answers "which of 10,000 stored
items are candidates?" without comparing every pair. Both are built from
scratch, so the whole dedupe stack is offline and free.
"""

import hashlib
import re
from collections import Counter

from ..text.stopwords import content_words
from ..text.tokenize import alphanumeric, shingles, words

_MASK64 = (1 << 64) - 1
_WORD_SPLIT = re.compile(r"\W+")


def _hash64(token: str, seed: int = 0) -> int:
    digest = hashlib.blake2b(f"{seed}:{token}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def simhash(text: str, *, bits: int = 64) -> int:
    """Weighted 64-bit SimHash over content-word tokens."""
    counts = Counter(content_words(words(text)))
    if not counts:
        return 0
    vector = [0] * bits
    for token, weight in counts.items():
        fingerprint = _hash64(token)
        for index in range(bits):
            vector[index] += weight if (fingerprint >> index) & 1 else -weight
    out = 0
    for index in range(bits):
        if vector[index] > 0:
            out |= 1 << index
    return out & _MASK64


def simhash_distance(a: int, b: int) -> int:
    return bin((a ^ b) & _MASK64).count("1")


def is_near_duplicate_hash(a: int, b: int, *, threshold: int = 6) -> bool:
    """Hamming distance <= threshold (~10% of bits) means near-duplicate."""
    return simhash_distance(a, b) <= threshold


def shingle_set(text: str, *, k: int = 5) -> set[str]:
    return shingles(text, k)


def minhash(text: str, *, permutations: int = 64, k: int = 5) -> tuple[int, ...]:
    """MinHash signature of the word-shingle set."""
    shingles_ = shingle_set(text, k=k) or {" ".join(alphanumeric(text))}
    signature = []
    for seed in range(permutations):
        signature.append(min(_hash64(shingle, seed) for shingle in shingles_))
    return tuple(signature)


def minhash_similarity(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    """Estimated Jaccard similarity from two signatures."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(1 for x, y in zip(a, b, strict=True) if x == y) / len(a)


def lsh_bands(signature: tuple[int, ...], *, rows: int = 4) -> list[str]:
    """Split a signature into bands for LSH bucketing."""
    if rows <= 0 or not signature:
        return []
    bands = []
    for start in range(0, len(signature) - rows + 1, rows):
        chunk = signature[start:start + rows]
        digest = hashlib.blake2b(repr(chunk).encode("utf-8"), digest_size=8).hexdigest()
        bands.append(f"{start // rows}:{digest}")
    return bands


class LSHIndex:
    """Band-based LSH store: add documents once, query candidates in O(bands)."""

    def __init__(self, *, permutations: int = 64, rows: int = 4, threshold: float = 0.55) -> None:
        self.permutations = permutations
        self.rows = rows
        self.threshold = threshold
        self.buckets: dict[str, set[str]] = {}
        self.signatures: dict[str, tuple[int, ...]] = {}
        self.hashes: dict[str, int] = {}

    def add(self, key: str, text: str) -> None:
        signature = minhash(text, permutations=self.permutations)
        self.signatures[key] = signature
        self.hashes[key] = simhash(text)
        for band in lsh_bands(signature, rows=self.rows):
            self.buckets.setdefault(band, set()).add(key)

    def candidates(self, text: str) -> list[str]:
        signature = minhash(text, permutations=self.permutations)
        found: set[str] = set()
        for band in lsh_bands(signature, rows=self.rows):
            found |= self.buckets.get(band, set())
        return sorted(found)

    def duplicates(self, text: str, *, key: str = "") -> list[tuple[str, float]]:
        """Candidates above the similarity threshold, best first."""
        signature = minhash(text, permutations=self.permutations)
        results = []
        for candidate in self.candidates(text):
            if candidate == key:
                continue
            score = minhash_similarity(signature, self.signatures[candidate])
            if score >= self.threshold:
                results.append((candidate, round(score, 4)))
        results.sort(key=lambda pair: -pair[1])
        return results

    def __len__(self) -> int:
        return len(self.signatures)

    def to_dict(self) -> dict:
        return {"signatures": {key: list(value) for key, value in self.signatures.items()},
                "hashes": {key: str(value) for key, value in self.hashes.items()}}

    @classmethod
    def from_dict(cls, payload: dict, *, permutations: int = 64, rows: int = 4) -> "LSHIndex":
        index = cls(permutations=permutations, rows=rows)
        for key, value in (payload.get("signatures") or {}).items():
            index.signatures[key] = tuple(value)
            for band in lsh_bands(index.signatures[key], rows=rows):
                index.buckets.setdefault(band, set()).add(key)
        for key, value in (payload.get("hashes") or {}).items():
            index.hashes[key] = int(value)
        return index


def cluster_by_hash(hashes: dict[str, int], *, threshold: int = 6) -> list[list[str]]:
    """Group stored items into duplicate clusters using SimHash distance."""
    keys = list(hashes)
    seen: set[str] = set()
    clusters: list[list[str]] = []
    for key in keys:
        if key in seen:
            continue
        group = [key]
        seen.add(key)
        for other in keys:
            if other in seen:
                continue
            if simhash_distance(hashes[key], hashes[other]) <= threshold:
                group.append(other)
                seen.add(other)
        clusters.append(group)
    return clusters


def fingerprint_text(text: str) -> dict:
    """Everything worth storing about one document's identity."""
    signature = minhash(text)
    return {"simhash": simhash(text), "minhash": list(signature),
            "bands": lsh_bands(signature), "shingles": len(shingle_set(text)),
            "tokens": len(_WORD_SPLIT.split(text.lower()))}


def shingle_overlap(a: str, b: str, *, k: int = 4) -> float:
    """Containment: what fraction of `a`'s k-word shingles also occur in `b`.

    Asymmetric on purpose — it answers "how much of this text is lifted from that
    text", which Jaccard cannot, because Jaccard shrinks when one side is longer.
    """
    first, second = shingle_set(a, k=k), shingle_set(b, k=k)
    if not first:
        return 0.0
    return len(first & second) / len(first)


def overlap_ratio(source: str, draft: str, *, k: int = 4) -> float:
    """How much of a draft's wording is copied from the source, 0..1."""
    return shingle_overlap(draft, source, k=k)


def unique_shingles(draft: str, source: str, *, k: int = 4) -> int:
    """Count of k-word phrases in the draft that the source never used."""
    first, second = shingle_set(draft, k=k), shingle_set(source, k=k)
    return len(first - second)
