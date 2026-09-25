"""Burst and velocity detection over topic time series.

A story that appears in five feeds within an hour is breaking; the same story
mentioned once a week is background noise. This module turns raw timestamps into
a burst score the ranking layer can use, with no external trend service needed.
"""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class Burst:
    term: str
    score: float
    z_score: float
    recent: int
    baseline: float
    velocity: float
    rising: bool

    def as_dict(self) -> dict:
        return {"term": self.term, "score": round(self.score, 4),
                "z_score": round(self.z_score, 3), "recent": self.recent,
                "baseline": round(self.baseline, 3), "velocity": round(self.velocity, 4),
                "rising": self.rising}


def bucket_counts(events: list[tuple[str, datetime]], *, bucket_minutes: int = 60) -> dict[str, list[int]]:
    """Term -> per-bucket counts over the whole observed window."""
    if not events:
        return {}
    start = min(when for _, when in events)
    end = max(when for _, when in events)
    buckets = max(1, int((end - start).total_seconds() // (bucket_minutes * 60)) + 1)
    series: dict[str, list[int]] = defaultdict(lambda: [0] * buckets)
    for term, when in events:
        index = min(buckets - 1, int((when - start).total_seconds() // (bucket_minutes * 60)))
        series[term][index] += 1
    return dict(series)


def z_score(values: list[float]) -> float:
    """Standardised distance of the latest value from the historical mean."""
    if len(values) < 2:
        return 0.0
    history = values[:-1]
    mean = sum(history) / len(history)
    variance = sum((value - mean) ** 2 for value in history) / len(history)
    deviation = math.sqrt(variance) or 1.0
    return (values[-1] - mean) / deviation


def velocity(values: list[float]) -> float:
    """Weighted slope of the last few buckets: positive means accelerating."""
    if len(values) < 2:
        return 0.0
    window = values[-4:]
    weights = [2 ** i for i in range(len(window))]
    weighted_mean = sum(value * weight for value, weight in zip(window, weights, strict=True)) / sum(weights)
    baseline = sum(window) / len(window)
    return round(weighted_mean - baseline, 4)


def exponential_smoothing(values: list[float], *, alpha: float = 0.35) -> list[float]:
    """Holt-style smoothing used to suppress single-bucket spikes."""
    if not values:
        return []
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1 - alpha) * out[-1])
    return out


def detect(events: list[tuple[str, datetime]], *, now: datetime | None = None,
           window_minutes: int = 180, bucket_minutes: int = 30,
           min_recent: int = 2) -> list[Burst]:
    """Rank terms by how hard they are bursting right now."""
    now = now or (max((when for _, when in events), default=datetime.now()))
    cutoff = now - timedelta(minutes=window_minutes)
    series = bucket_counts(events, bucket_minutes=bucket_minutes)
    recent_counts = Counter(term for term, when in events if when >= cutoff)
    bursts: list[Burst] = []
    for term, values in series.items():
        recent = recent_counts.get(term, 0)
        if recent < min_recent:
            continue
        smoothed = exponential_smoothing([float(value) for value in values])
        zscore = z_score(smoothed)
        slope = velocity(smoothed)
        baseline = sum(values[:-1]) / max(1, len(values) - 1) if len(values) > 1 else 0.0
        score = (
            0.45 * min(1.0, recent / 6)
            + 0.30 * min(1.0, max(0.0, zscore) / 3)
            + 0.15 * min(1.0, max(0.0, slope))
            + 0.10 * (1.0 if recent > baseline * 2 else 0.0)
        )
        bursts.append(Burst(term=term, score=round(score, 4), z_score=round(zscore, 3),
                            recent=recent, baseline=baseline, velocity=slope,
                            rising=zscore > 0.6 or slope > 0.15))
    bursts.sort(key=lambda burst: (-burst.score, burst.term))
    return bursts


def is_breaking(term: str, events: list[tuple[str, datetime]], *, now: datetime | None = None,
                window_minutes: int = 120, min_mentions: int = 3) -> bool:
    """True when a term is spiking right now — the 'breaking news' gate."""
    now = now or datetime.now()
    cutoff = now - timedelta(minutes=window_minutes)
    mentions = sum(1 for candidate, when in events if candidate == term and when >= cutoff)
    if mentions < min_mentions:
        return False
    total = sum(1 for candidate, _ in events if candidate == term)
    return mentions / max(1, total) > 0.6


def heat(events: list[tuple[str, datetime]], *, now: datetime | None = None,
         half_life_minutes: int = 240) -> dict[str, float]:
    """Exponentially decayed mention heat — recent mentions count for more."""
    now = now or datetime.now()
    out: dict[str, float] = defaultdict(float)
    for term, when in events:
        age = max(0.0, (now - when).total_seconds() / 60)
        out[term] += 0.5 ** (age / half_life_minutes)
    return {term: round(value, 4) for term, value in out.items()}


def acceleration(events: list[tuple[str, datetime]], term: str, *,
                 bucket_minutes: int = 60) -> float:
    """Second derivative of mentions: is the spike still steepening?"""
    series = bucket_counts([(candidate, when) for candidate, when in events if candidate == term],
                           bucket_minutes=bucket_minutes).get(term, [])
    if len(series) < 3:
        return 0.0
    slopes = [series[i + 1] - series[i] for i in range(len(series) - 1)]
    return round(slopes[-1] - slopes[-2], 4)
