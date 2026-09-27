"""Smart story selection: freshness decay, source weight, multi-source
"hotness" (how many outlets cover the same story), trends, keywords,
and diversity caps per source and category."""

from __future__ import annotations

import math
from collections import Counter

from .dedupe import cluster, keywords
from .feeds import FeedItem
from .trends import trend_match
from .utils import hours_since


class Ranker:
    def __init__(self, settings, trending_terms: list[str] | None = None) -> None:
        r = settings.get("ranking", {})
        self.half_life = float(r.get("freshness_half_life_hours", 10))
        self.trend_boost = float(r.get("trend_boost", 12))
        self.keyword_boost = float(r.get("keyword_boost", 3))
        self.priority = {k.lower() for k in r.get("priority_keywords", [])}
        self.similarity = float(r.get("cluster_similarity", 0.55))
        self.trending = trending_terms or []

    def score(self, item: FeedItem) -> float:
        notes: list[str] = []
        age = hours_since(item.published) if item.published else 12.0
        freshness = 50.0 * math.pow(0.5, age / self.half_life)
        notes.append(f"fresh {freshness:.0f}")
        score = freshness

        weight_bonus = 10.0 * (item.feed_weight - 1.0)
        if weight_bonus:
            score += weight_bonus
            notes.append(f"source {weight_bonus:+.0f}")

        if item.cluster_size > 1:
            hot = min(30.0, 9.0 * (item.cluster_size - 1))
            score += hot
            notes.append(f"covered by {item.cluster_size} outlets +{hot:.0f}")

        hits = self.priority & keywords(item.title)
        if hits:
            kb = min(12.0, self.keyword_boost * len(hits))
            score += kb
            notes.append(f"keywords {','.join(sorted(hits))} +{kb:.0f}")

        trend = trend_match(item.title, self.trending)
        if trend:
            score += self.trend_boost
            notes.append(f"trending '{trend}' +{self.trend_boost:.0f}")

        if item.image:
            score += 3
        if len(item.summary) > 200:
            score += 2
        item.score = round(score, 2)
        item.score_notes = notes
        return item.score

    def rank(self, items: list[FeedItem]) -> list[FeedItem]:
        """Cluster duplicates, keep the best representative per story, sort by score."""
        # Sort so the best source (weight) and freshest item becomes the representative
        items = sorted(items, key=lambda it: (-it.feed_weight, hours_since(it.published)))
        reps: list[FeedItem] = []
        for group in cluster(items, threshold=self.similarity):
            best = group[0]
            best.cluster_size = len({g.host for g in group})
            best.related_sources = sorted({g.source for g in group if g.source != best.source})[:5]
            reps.append(best)
        for it in reps:
            self.score(it)
        return sorted(reps, key=lambda it: it.score, reverse=True)


def diversify(items: list[FeedItem], max_per_source: int, max_per_category: int, limit: int) -> list[FeedItem]:
    """Pick up to *limit* items while respecting per-source/category caps."""
    picked: list[FeedItem] = []
    per_source: Counter = Counter()
    per_cat: Counter = Counter()
    for it in items:
        if len(picked) >= limit:
            break
        if max_per_source and per_source[it.host] >= max_per_source:
            continue
        if max_per_category and per_cat[it.category] >= max_per_category:
            continue
        picked.append(it)
        per_source[it.host] += 1
        per_cat[it.category] += 1
    return picked
