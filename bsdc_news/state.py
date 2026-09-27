"""Persistent JSON state (committed back to the repo by the workflow).

Tracks what was published, what failed (with retry back-off), daily quotas,
AI provider health and consecutive failed runs, so the bot never re-posts
the same story and never burns quota twice.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from .log import get_logger, mask
from .utils import canonical_url, iso, parse_iso, short_hash, today_key, utcnow

log = get_logger("state")

SCHEMA_VERSION = 2


def _empty() -> dict:
    return {
        "version": SCHEMA_VERSION,
        "published": {},      # key -> {title, url, post_url, post_id, source, category, at, words, ...}
        "failed": {},         # key -> {title, url, attempts, last_at, reason}
        "seen_titles": {},    # title fingerprint -> at
        "quota": {},          # name -> {day: count}
        "providers": {},      # provider -> {disabled_until, last_error, successes, failures}
        "indexing_queue": [],  # post urls waiting for Google Indexing API quota
        "runs": {"consecutive_failures": 0, "last_run": None, "last_success": None, "total": 0},
        "blog": {},           # cached blog info (url, name)
        "meta": {},           # misc flags (e.g. rebuilt_from_blog)
    }


class State:
    def __init__(self, path: Path, data: dict | None = None) -> None:
        self.path = Path(path)
        self.data = data or _empty()
        self.dirty = False
        self.readonly = False  # dry runs must never mark stories as published

    # ── io ──
    @classmethod
    def load(cls, path: Path) -> State:
        path = Path(path)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                base = _empty()
                base.update({k: v for k, v in raw.items() if k in base})
                base["runs"] = {**_empty()["runs"], **(raw.get("runs") or {})}
                base["version"] = SCHEMA_VERSION
                return cls(path, base)
            except (OSError, ValueError) as exc:
                backup = path.with_suffix(".corrupt.json")
                log.warning("State file unreadable (%s) — starting fresh, old copy kept at %s", exc, backup)
                try:
                    path.replace(backup)
                except OSError:
                    pass
        return cls(path)

    def save(self) -> None:
        if self.readonly:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=1, sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload + "\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        self.dirty = False

    # ── keys ──
    @staticmethod
    def key_for(url: str) -> str:
        return short_hash(canonical_url(url), 20)

    # ── published / seen ──
    def is_published(self, url: str) -> bool:
        return self.key_for(url) in self.data["published"]

    def title_seen(self, fingerprint: str) -> bool:
        return bool(fingerprint) and fingerprint in self.data["seen_titles"]

    def mark_published(self, url: str, record: dict, fingerprint: str = "") -> None:
        key = self.key_for(url)
        self.data["published"][key] = {**record, "url": url, "at": iso()}
        self.data["failed"].pop(key, None)
        if fingerprint:
            self.data["seen_titles"][fingerprint] = iso()
        self.dirty = True

    def published_records(self) -> list[dict]:
        return sorted(self.data["published"].values(), key=lambda r: r.get("at", ""), reverse=True)

    def remember_title(self, fingerprint: str) -> None:
        if fingerprint:
            self.data["seen_titles"][fingerprint] = iso()
            self.dirty = True

    # ── failures with back-off ──
    def record_failure(self, url: str, title: str, reason: str, permanent: bool = False) -> None:
        key = self.key_for(url)
        entry = self.data["failed"].get(key, {"title": title, "url": url, "attempts": 0})
        entry["attempts"] = int(entry.get("attempts", 0)) + (99 if permanent else 1)
        entry["last_at"] = iso()
        entry["reason"] = mask(reason)[:300]
        self.data["failed"][key] = entry
        self.dirty = True

    def should_skip_failed(self, url: str, retry_hours: float, max_attempts: int) -> bool:
        entry = self.data["failed"].get(self.key_for(url))
        if not entry:
            return False
        if int(entry.get("attempts", 0)) >= max_attempts:
            return True
        last = parse_iso(entry.get("last_at"))
        return bool(last and utcnow() - last < timedelta(hours=retry_hours))

    # ── quotas ──
    def quota_used(self, name: str, tz: str = "UTC") -> int:
        return int(self.data["quota"].get(name, {}).get(today_key(tz), 0))

    def quota_add(self, name: str, amount: int = 1, tz: str = "UTC") -> None:
        day = today_key(tz)
        bucket = self.data["quota"].setdefault(name, {})
        bucket[day] = int(bucket.get(day, 0)) + amount
        for old in sorted(bucket)[:-3]:  # keep only recent days
            bucket.pop(old, None)
        self.dirty = True

    # ── providers ──
    def provider(self, name: str) -> dict:
        return self.data["providers"].setdefault(name, {"successes": 0, "failures": 0})

    def provider_disabled(self, name: str, key_fp: str = "") -> bool:
        info = self.provider(name)
        until = parse_iso(info.get("disabled_until"))
        if not until or until <= utcnow():
            return False
        # The owner rotated the key since the provider was paused → try again immediately
        return not (key_fp and info.get("key_fp") and info["key_fp"] != key_fp)

    def disable_provider(self, name: str, until, reason: str, key_fp: str = "") -> None:
        info = self.provider(name)
        info["disabled_until"] = iso(until)
        info["last_error"] = mask(reason)[:300]
        if key_fp:
            info["key_fp"] = key_fp
        self.dirty = True

    def provider_result(self, name: str, ok: bool, error: str = "") -> None:
        info = self.provider(name)
        if ok:
            info["successes"] = int(info.get("successes", 0)) + 1
            info.pop("disabled_until", None)
            info["last_ok"] = iso()
        else:
            info["failures"] = int(info.get("failures", 0)) + 1
            info["last_error"] = mask(error)[:300]
        self.dirty = True

    # ── indexing queue ──
    def queue_for_indexing(self, urls: list[str]) -> None:
        queue = self.data["indexing_queue"]
        for url in urls:
            if url and url not in queue:
                queue.append(url)
        self.data["indexing_queue"] = queue[-500:]
        self.dirty = True

    def pop_indexing(self, limit: int) -> list[str]:
        queue = self.data["indexing_queue"]
        batch, self.data["indexing_queue"] = queue[:limit], queue[limit:]
        if batch:
            self.dirty = True
        return batch

    def requeue_indexing(self, urls: list[str]) -> None:
        self.data["indexing_queue"] = list(urls) + [u for u in self.data["indexing_queue"] if u not in urls]
        self.dirty = True

    # ── runs ──
    def record_run(self, success: bool) -> int:
        runs = self.data["runs"]
        runs["total"] = int(runs.get("total", 0)) + 1
        runs["last_run"] = iso()
        if success:
            runs["consecutive_failures"] = 0
            runs["last_success"] = iso()
        else:
            runs["consecutive_failures"] = int(runs.get("consecutive_failures", 0)) + 1
        self.dirty = True
        return runs["consecutive_failures"]

    # ── housekeeping ──
    def prune(self, retention_days: int) -> int:
        cutoff = utcnow() - timedelta(days=retention_days)
        removed = 0
        for section in ("published", "failed"):
            for key in list(self.data[section]):
                ts = parse_iso(self.data[section][key].get("at") or self.data[section][key].get("last_at"))
                if ts and ts < cutoff:
                    del self.data[section][key]
                    removed += 1
        for fp in list(self.data["seen_titles"]):
            ts = parse_iso(self.data["seen_titles"][fp])
            if ts and ts < cutoff:
                del self.data["seen_titles"][fp]
                removed += 1
        if removed:
            self.dirty = True
        return removed

    def stats(self) -> dict[str, Any]:
        return {
            "published_tracked": len(self.data["published"]),
            "failed_tracked": len(self.data["failed"]),
            "indexing_queue": len(self.data["indexing_queue"]),
            "consecutive_failures": self.data["runs"].get("consecutive_failures", 0),
        }
