"""Small, dependency-free helpers shared by many modules."""

from __future__ import annotations

import calendar
import hashlib
import html
import json
import re
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


# ─────────────────────────── time ───────────────────────────


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    dt = dt or utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(str(value))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def from_struct_time(value: Any) -> datetime | None:
    """feedparser returns time.struct_time in UTC."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def hours_since(dt: datetime | None, now: datetime | None = None) -> float:
    if dt is None:
        return 1e9
    now = now or utcnow()
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def get_zone(name: str | None):
    if not name or ZoneInfo is None:
        return UTC
    try:
        return ZoneInfo(name)
    except Exception:
        return UTC


def next_midnight(tz_name: str = "America/Los_Angeles", now: datetime | None = None) -> datetime:
    """Next local midnight in *tz_name*, returned in UTC (quota reset times)."""
    tz = get_zone(tz_name)
    local = (now or utcnow()).astimezone(tz)
    tomorrow = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.astimezone(UTC)


def paced_allowance(max_per_day: int, tz_name: str, now: datetime | None = None, lead_minutes: int = 90) -> int:
    """How many posts may have been published *so far today* to spread ``max_per_day`` evenly
    over the local day (with a small lead so the first run after midnight can post)."""
    local = (now or utcnow()).astimezone(get_zone(tz_name))
    minutes = local.hour * 60 + local.minute + lead_minutes
    return min(max_per_day, max(1, -(-max_per_day * minutes // 1440)))


def today_key(tz_name: str = "UTC", now: datetime | None = None) -> str:
    return (now or utcnow()).astimezone(get_zone(tz_name)).strftime("%Y-%m-%d")


def in_time_window(window: str, tz_name: str, now: datetime | None = None) -> bool:
    """True when local time is inside a window such as ``"01:00-06:00"`` (may wrap midnight)."""
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", window or "")
    if not match:
        return False
    h1, m1, h2, m2 = (int(x) for x in match.groups())
    local = (now or utcnow()).astimezone(get_zone(tz_name))
    minutes = local.hour * 60 + local.minute
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if start == end:
        return False
    if start < end:
        return start <= minutes < end
    return minutes >= start or minutes < end


# ─────────────────────────── text ───────────────────────────

_WS_RE = re.compile(r"[ \t\u00a0\u2000-\u200b\u202f\u205f\u3000]+")
_TAG_RE = re.compile(r"<[^>]+>")


def normalize_space(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = _WS_RE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_tags(markup: str | None) -> str:
    if not markup:
        return ""
    return normalize_space(html.unescape(_TAG_RE.sub(" ", markup)))


def word_count(text: str | None) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text or ""))


def truncate(text: str, limit: int, ellipsis: str = "…") -> str:
    text = normalize_space(text)
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - len(ellipsis))]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-–—") + ellipsis


def slugify(text: str, max_len: int = 70) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0]
    return text or "post"


def short_hash(text: str, length: int = 16) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:length]


def esc(text: Any) -> str:
    """HTML-escape any value for safe use in markup and attributes."""
    return html.escape("" if text is None else str(text), quote=True)


def json_for_html(obj: Any) -> str:
    """JSON that is safe to embed inside a <script> tag (same approach as Django's json_script):
    <, > and & are unicode-escaped so no markup can ever break out of the script element."""
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return raw.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ─────────────────────────── urls ───────────────────────────

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src", "ref_url",
    "cmpid", "cid", "src", "source", "feature", "guccounter", "guce_referrer", "_ga",
    "ocid", "taid", "smid", "partner", "rss", "output", "utm",
}


def is_http_url(url: str | None) -> bool:
    if not url:
        return False
    try:
        parts = urlsplit(str(url).strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def absolutize(url: str | None, base: str | None) -> str:
    if not url:
        return ""
    url = html.unescape(str(url).strip())
    if url.startswith("//"):
        url = "https:" + url
    if base:
        url = urljoin(base, url)
    return url if is_http_url(url) else ""


def canonical_url(url: str | None) -> str:
    """Normalise a URL for de-duplication (drops tracking params, fragments, AMP, www)."""
    if not url:
        return ""
    try:
        parts = urlsplit(str(url).strip())
    except ValueError:
        return str(url).strip()
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    host = host.removesuffix(":443").removesuffix(":80")
    path = re.sub(r"/+", "/", parts.path or "/")
    path = re.sub(r"/(amp|amp\.html)$", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    query.sort()
    return urlunsplit(("https", host, path, urlencode(query), ""))


def host_of(url: str | None) -> str:
    try:
        host = urlsplit(url or "").netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


# ─────────────────────────── misc ───────────────────────────


class Stopwatch:
    def __init__(self) -> None:
        self.start = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start


def dedupe_keep_order(items, key=lambda x: x):
    seen: set = set()
    out = []
    for item in items:
        k = key(item)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out
