"""Search-engine notification.

* Google Indexing API  — fixed scope (was a corrupted markdown link), daily
  quota tracking, queue for URLs that did not fit today's quota, clear hints
  for 403 (service account must be an *Owner* in Search Console).
* IndexNow (Bing, Yandex, Seznam, Naver…) — fixed endpoint (was a corrupted
  markdown link); only runs when a key is configured *and* the key file is
  reachable on the site, because IndexNow rejects unverifiable keys.
* WebSub / PubSubHubbub ping for the blog feed (free, instant feed readers).
* Bing Webmaster URL Submission API (optional free API key).
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from ..http import HttpClient
from ..log import get_logger

log = get_logger("indexing")

INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing"
INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
WEBSUB_HUBS = ["https://pubsubhubbub.appspot.com/", "https://pubsubhubbub.superfeedr.com/"]
BING_SUBMIT = "https://ssl.bing.com/webmaster/api.svc/json/SubmitUrlbatch"


class GoogleIndexer:
    def __init__(self, service_account_json: str, daily_quota: int = 200) -> None:
        self.info = None
        self.daily_quota = daily_quota
        self.error = ""
        if service_account_json:
            try:
                self.info = json.loads(service_account_json)
            except ValueError:
                self.error = "INDEXING_SERVICE_ACCOUNT_JSON is not valid JSON"
        self._session = None

    @property
    def available(self) -> bool:
        return bool(self.info)

    def session(self):
        if self._session is None:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_info(self.info, scopes=[INDEXING_SCOPE])
            self._session = AuthorizedSession(creds)
        return self._session

    def publish(self, urls: list[str], kind: str = "URL_UPDATED") -> tuple[list[str], list[str], str]:
        """Returns (ok_urls, failed_urls, fatal_error)."""
        if not self.info:
            return [], list(urls), ("Google Indexing API not configured — set "
                                    "INDEXING_SERVICE_ACCOUNT_JSON (free) to enable it")
        ok, failed = [], []
        for idx, url in enumerate(urls):
            try:
                resp = self.session().post(INDEXING_ENDPOINT, json={"url": url, "type": kind}, timeout=20)
            except Exception as exc:
                text = str(exc)
                hint = ""
                if "No access token" in text or "invalid_scope" in text:
                    hint = " (the OAuth scope is wrong or the key is revoked)"
                return ok, failed + urls[idx:], f"Google Indexing auth failed: {text[:200]}{hint}"
            if resp.status_code == 200:
                ok.append(url)
                continue
            body = resp.text[:300]
            if resp.status_code == 429:
                return ok, failed + urls[idx:], "Google Indexing API daily quota exhausted"
            if resp.status_code == 403:
                return ok, failed + urls[idx:], (
                    "Google Indexing API permission denied — add the service account e-mail "
                    f"({(self.info or {}).get('client_email', '?')}) as an OWNER of the property in Google "
                    "Search Console and enable the 'Web Search Indexing API' in its Cloud project. "
                    f"Details: {body[:150]}")
            failed.append(url)
            log.debug("Indexing API %s for %s: %s", resp.status_code, url, body)
        return ok, failed, ""


class Indexer:
    def __init__(self, settings, http: HttpClient, state) -> None:
        self.settings = settings
        self.http = http
        self.state = state
        self.tz = "America/Los_Angeles"  # Google quotas reset at midnight Pacific
        self.google = GoogleIndexer(settings.secret("indexing_service_account_json"),
                                    int(settings.get("indexing.google_daily_quota", 200)))
        self.indexnow_key = settings.secret("indexnow_key")
        self.bing_key = settings.secret("bing_api_key")
        self.results: dict[str, str] = {}
        self._indexnow_verified: bool | None = None

    # ── Google ──
    def google_submit(self, new_urls: list[str]) -> None:
        if not self.settings.get("indexing.google_indexing_api", True):
            return
        if not self.google.available:
            if self.google.error:
                self.results["google"] = self.google.error
                log.warning("Google Indexing API skipped: %s", self.google.error)
            return
        self.state.queue_for_indexing(new_urls)
        remaining = self.google.daily_quota - self.state.quota_used("google_indexing", self.tz)
        if remaining <= 0:
            self.results["google"] = "daily quota already used — URLs queued for tomorrow"
            log.info("   ⏳ Google Indexing quota used for today; %d URL(s) queued",
                     len(self.state.data["indexing_queue"]))
            return
        batch = self.state.pop_indexing(min(remaining, 50))
        ok, failed, fatal = self.google.publish(batch)
        if ok:
            self.state.quota_add("google_indexing", len(ok), self.tz)
            log.info("   🔎 Google Indexing API: %d URL(s) submitted", len(ok))
        if failed:
            self.state.requeue_indexing(failed)
        if fatal:
            self.results["google"] = fatal
            log.warning("Google Indexing API: %s", fatal)
        else:
            self.results["google"] = f"{len(ok)} submitted"

    # ── IndexNow ──
    def _key_location(self, host: str) -> str:
        configured = self.settings.get("indexing.indexnow_key_location", "")
        return configured or f"https://{host}/{self.indexnow_key}.txt"

    def indexnow_ready(self, host: str) -> bool:
        if self._indexnow_verified is not None:
            return self._indexnow_verified
        if not self.indexnow_key:
            self._indexnow_verified = False
            return False
        try:
            resp = self.http.get(self._key_location(host), timeout=10, api=True)
            self._indexnow_verified = resp.status_code == 200 and self.indexnow_key in resp.text[:512]
        except Exception:
            self._indexnow_verified = False
        if not self._indexnow_verified:
            log.info("   ℹ️ IndexNow skipped: key file %s not reachable (see docs/SEO.md)", self._key_location(host))
        return self._indexnow_verified

    def indexnow_submit(self, urls: list[str]) -> None:
        if not urls or not self.settings.get("indexing.indexnow", True):
            return
        host = urlsplit(urls[0]).netloc
        if not self.indexnow_ready(host):
            self.results["indexnow"] = "skipped (no verified key)"
            return
        payload = {"host": host, "key": self.indexnow_key, "keyLocation": self._key_location(host),
                   "urlList": [u for u in urls if urlsplit(u).netloc == host][:10000]}
        try:
            resp = self.http.post(INDEXNOW_ENDPOINT, json=payload, timeout=15,
                                  headers={"Content-Type": "application/json; charset=utf-8"})
            self.results["indexnow"] = f"HTTP {resp.status_code}"
            if resp.status_code in (200, 202):
                log.info("   🔎 IndexNow accepted %d URL(s)", len(payload["urlList"]))
            else:
                log.warning("IndexNow HTTP %s: %s", resp.status_code, resp.text[:150])
        except Exception as exc:
            self.results["indexnow"] = f"error: {exc}"
            log.warning("IndexNow error: %s", exc)

    # ── Bing URL Submission API ──
    def bing_submit(self, urls: list[str], site_url: str) -> None:
        if not (urls and self.bing_key and site_url):
            return
        try:
            resp = self.http.post(BING_SUBMIT, params={"apikey": self.bing_key},
                                  json={"siteUrl": site_url, "urlList": urls[:500]}, timeout=15)
            self.results["bing"] = f"HTTP {resp.status_code}"
            if resp.status_code == 200:
                log.info("   🔎 Bing URL Submission API accepted %d URL(s)", len(urls))
        except Exception as exc:
            self.results["bing"] = f"error: {exc}"

    # ── WebSub ──
    def websub_ping(self, site_url: str) -> None:
        if not (site_url and self.settings.get("indexing.websub_ping", True)):
            return
        feeds = [f"{site_url.rstrip('/')}/feeds/posts/default", f"{site_url.rstrip('/')}/feeds/posts/default?alt=rss"]
        pinged = 0
        for hub in WEBSUB_HUBS:
            for feed in feeds:
                try:
                    resp = self.http.post(hub, data={"hub.mode": "publish", "hub.url": feed}, timeout=10)
                    pinged += int(resp.status_code in (200, 202, 204))
                except Exception:
                    continue
        self.results["websub"] = f"{pinged} pings accepted"
        if pinged:
            log.info("   📡 WebSub hubs notified (%d)", pinged)

    def run(self, new_urls: list[str], site_url: str) -> dict[str, str]:
        if new_urls or self.state.data.get("indexing_queue"):
            self.google_submit(new_urls)
        if new_urls:
            self.indexnow_submit(new_urls)
            self.bing_submit(new_urls, site_url)
            self.websub_ping(site_url)
        return self.results
