"""Shared HTTP client: retries with back-off, polite per-host pacing,
robots.txt awareness, size limits and an optional Cloudflare-bypass fallback."""

from __future__ import annotations

import random
import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from requests.structures import CaseInsensitiveDict
from urllib3.util.retry import Retry

from . import __version__
from .log import get_logger

log = get_logger("http")

BOT_TOKEN = "bsdcNewsBot"
BROWSER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:142.0) Gecko/20100101 Firefox/142.0",
]
API_AGENT = f"{BOT_TOKEN}/{__version__} (+https://github.com/bsdc-info-bd/bsdc-news-bot)"
MAX_BYTES = 6 * 1024 * 1024
CHALLENGE_MARKERS = ("cf-chl", "challenge-platform", "just a moment...", "attention required")


@dataclass
class SimpleResponse:
    """Minimal response object (also used by the test doubles)."""

    status_code: int
    text: str = ""
    content: bytes = b""
    headers: dict | None = None
    url: str = ""

    def json(self):
        import json

        return json.loads(self.text or self.content.decode("utf-8", "replace"))

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400


class HttpClient:
    def __init__(
        self,
        timeout: float = 20.0,
        retries: int = 2,
        per_host_interval: float = 0.8,
        respect_robots: bool = True,
    ) -> None:
        self.timeout = timeout
        self.per_host_interval = per_host_interval
        self.respect_robots = respect_robots
        self.session = requests.Session()
        retry = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._browser_agent = random.choice(BROWSER_AGENTS)
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()
        self._scraper = None

    # ── low level ──
    def _pace(self, url: str) -> None:
        host = urlsplit(url).netloc
        with self._lock:
            wait = self._last_hit.get(host, 0) + self.per_host_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_hit[host] = time.monotonic()

    def browser_headers(self, extra: dict | None = None) -> dict:
        headers = {
            "User-Agent": self._browser_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        }
        headers.update(extra or {})
        return headers

    def get(self, url: str, *, headers: dict | None = None, timeout: float | None = None,
            params: dict | None = None, stream: bool = False, api: bool = False,
            allow_redirects: bool = True):
        self._pace(url)
        hdrs = {"User-Agent": API_AGENT} if api else self.browser_headers()
        hdrs.update(headers or {})
        return self.session.get(url, headers=hdrs, timeout=timeout or self.timeout, params=params,
                                stream=stream, allow_redirects=allow_redirects)

    def head(self, url: str, *, headers: dict | None = None, timeout: float | None = None):
        self._pace(url)
        hdrs = self.browser_headers()
        hdrs.update(headers or {})
        return self.session.head(url, headers=hdrs, timeout=timeout or 8, allow_redirects=True)

    def post(self, url: str, *, json=None, data=None, headers: dict | None = None,
             timeout: float | None = None, params: dict | None = None):
        hdrs = {"User-Agent": API_AGENT}
        hdrs.update(headers or {})
        return self.session.post(url, json=json, data=data, headers=hdrs, params=params,
                                 timeout=timeout or self.timeout)

    def get_bytes(self, url: str, limit: int = 65536, timeout: float = 10.0) -> tuple[int, dict, bytes]:
        """Download at most *limit* bytes (used to sniff image dimensions)."""
        resp = self.get(url, headers={"Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                                      "Range": f"bytes=0-{limit - 1}"}, timeout=timeout, stream=True)
        try:
            chunks, size = [], 0
            for chunk in resp.iter_content(8192):
                chunks.append(chunk)
                size += len(chunk)
                if size >= limit:
                    break
            return resp.status_code, CaseInsensitiveDict(resp.headers), b"".join(chunks)[:limit]
        finally:
            resp.close()

    # ── robots.txt ──
    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            parser: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            try:
                resp = self.session.get(base + "/robots.txt", timeout=6,
                                        headers={"User-Agent": API_AGENT})
                if resp.status_code >= 400:
                    parser = None  # no robots.txt -> everything allowed
                else:
                    parser.parse(resp.text.splitlines())
            except requests.RequestException:
                parser = None
            self._robots[base] = parser
        parser = self._robots[base]
        if parser is None:
            return True
        return parser.can_fetch(BOT_TOKEN, url)

    # ── html pages ──
    def fetch_html(self, url: str, timeout: float | None = None) -> SimpleResponse:
        """GET an article page; transparently retries through cloudscraper on bot walls."""
        try:
            resp = self.get(url, timeout=timeout, stream=True)
            content = self._read_capped(resp)
            final = SimpleResponse(resp.status_code, self._decode(resp, content), content,
                                   CaseInsensitiveDict(resp.headers), resp.url)
        except requests.RequestException as exc:
            log.debug("GET failed for %s: %s", url, exc)
            final = SimpleResponse(0, "", b"", CaseInsensitiveDict(), url)

        blocked = final.status_code in (0, 403, 429, 503) or any(
            m in final.text[:4000].lower() for m in CHALLENGE_MARKERS)
        if blocked:
            alt = self._cloudscraper_get(url, timeout)
            if alt is not None and alt.status_code == 200:
                return alt
        return final

    def _cloudscraper_get(self, url: str, timeout: float | None) -> SimpleResponse | None:
        try:
            if self._scraper is None:
                import cloudscraper  # optional dependency

                self._scraper = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False})
            self._pace(url)
            resp = self._scraper.get(url, timeout=timeout or self.timeout)
            return SimpleResponse(resp.status_code, resp.text, resp.content, CaseInsensitiveDict(resp.headers), resp.url)
        except Exception as exc:  # cloudscraper missing or blocked
            log.debug("cloudscraper fallback failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _read_capped(resp) -> bytes:
        chunks, size = [], 0
        for chunk in resp.iter_content(16384):
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                break
        resp.close()
        return b"".join(chunks)

    @staticmethod
    def _decode(resp, content: bytes) -> str:
        encoding = resp.encoding
        if not encoding or encoding.lower() == "iso-8859-1":
            encoding = getattr(resp, "apparent_encoding", None) or "utf-8"
        try:
            return content.decode(encoding, "replace")
        except LookupError:
            return content.decode("utf-8", "replace")
