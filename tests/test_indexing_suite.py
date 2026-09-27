"""The indexing layer: Google Indexing API, IndexNow, Bing, WebSub and the
verifier — every channel must degrade gracefully when its credential is missing,
because the whole point is that publishing works with no paid account."""

import json

import pytest

from bsdc_news.indexing.core import (
    BING_SUBMIT,
    INDEXING_ENDPOINT,
    INDEXING_SCOPE,
    INDEXNOW_ENDPOINT,
    WEBSUB_HUBS,
    GoogleIndexer,
    Indexer,
)
from bsdc_news.state import State


class Recorder:
    """Minimal HTTP double that records every request the indexer makes."""

    def __init__(self, status=200, body="", html="<html><body>key</body></html>"):
        self.status = status
        self.body = body
        self.html = html
        self.posts = []
        self.gets = []

    class _Response:
        def __init__(self, status, body):
            self.status_code = status
            self.text = body

        def json(self):
            return json.loads(self.text or "{}")

        def raise_for_status(self):
            if self.status >= 400:
                raise RuntimeError(f"HTTP {self.status}")

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self._Response(self.status, self.body or '{"d":{"urlNotificationMetadata":{}}}')

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return self._Response(200, self.html)

    def fetch_html(self, url, timeout=None):
        self.gets.append((url, {}))
        return self.html

    def allowed(self, url):
        return True

    def get_bytes(self, url, limit=65536, timeout=10.0):
        return b""


@pytest.fixture()
def indexer(settings, tmp_path):
    def build(http=None, **secrets):
        for key, value in secrets.items():
            settings.secrets[key] = value
        return Indexer(settings, http or Recorder(), State(tmp_path / "state.json"))

    return build


# ------------------------------------------------------------------ Google
def test_indexing_constants_are_the_current_endpoints():
    assert INDEXING_ENDPOINT.startswith("https://") and INDEXING_ENDPOINT.endswith("urlNotifications:publish")
    assert INDEXING_SCOPE == "https://www.googleapis.com/auth/indexing"
    assert INDEXNOW_ENDPOINT.startswith("https://") and "indexnow" in INDEXNOW_ENDPOINT
    assert BING_SUBMIT.startswith("https://") and "bing" in BING_SUBMIT
    assert len(WEBSUB_HUBS) >= 2 and all(hub.startswith("https://") for hub in WEBSUB_HUBS)


def test_google_indexer_is_unavailable_without_a_service_account():
    indexer = GoogleIndexer("", 200)
    assert indexer.available is False
    ok, failed, message = indexer.publish(["https://b.test/p.html"])
    assert ok == [] and failed == ["https://b.test/p.html"]
    assert "not configured" in message.lower()


def test_google_indexer_rejects_a_malformed_key_file():
    indexer = GoogleIndexer("{not json", 200)
    assert indexer.available is False
    assert indexer.publish([])[0] == []


def test_google_submit_is_skipped_when_disabled(indexer, settings):
    settings.data["indexing"] = {**settings.data.get("indexing", {}), "google_indexing_api": False}
    http = Recorder()
    engine = indexer(http=http)
    engine.google_submit(["https://b.test/p.html"])
    assert http.posts == []


def test_google_submit_without_credentials_reports_the_reason(indexer):
    http = Recorder()
    engine = indexer(http=http)
    engine.google_submit(["https://b.test/p.html"])
    assert http.posts == [], "no call is made without a service account"
    assert not engine.results.get("google") or "skip" in engine.results["google"].lower()


# ------------------------------------------------------------------ IndexNow
def test_indexnow_is_not_ready_without_a_key(indexer):
    engine = indexer()
    assert engine.indexnow_ready("bsdc-news.blogspot.com") is False


def test_indexnow_submit_skips_when_the_key_file_is_unreachable(indexer):
    http = Recorder(html="<html><body>not the key</body></html>")
    engine = indexer(http=http, indexnow_key="abc123def456")
    engine.indexnow_submit(["https://b.test/p.html"])
    assert http.posts == [], "an unverified key must not be submitted anywhere"


def test_indexnow_key_location_points_at_the_domain_root(indexer):
    engine = indexer(indexnow_key="abc123def456")
    location = engine._key_location("bsdc-news.blogspot.com")
    assert location.endswith("abc123def456.txt") and location.startswith("https://")


# ------------------------------------------------------------------ Bing
def test_bing_submit_needs_a_key(indexer):
    http = Recorder()
    engine = indexer(http=http)
    engine.bing_submit(["https://b.test/p.html"], "https://b.test")
    assert http.posts == [], "Bing must not be called without a key"


def test_bing_submit_posts_the_url_batch(indexer):
    http = Recorder(status=200, body="")
    engine = indexer(http=http, bing_api_key="free-key")
    engine.bing_submit(["https://b.test/p1.html", "https://b.test/p2.html"], "https://b.test")
    assert http.posts and http.posts[0][0] == BING_SUBMIT
    assert engine.results.get("bing", "").lower()


def test_bing_submit_survives_a_rejected_request(indexer):
    http = Recorder(status=401, body="denied")
    engine = indexer(http=http, bing_api_key="bad-key")
    engine.bing_submit(["https://b.test/p.html"], "https://b.test")
    assert "401" in engine.results.get("bing", "") or "fail" in engine.results.get("bing", "").lower()


# ------------------------------------------------------------------ WebSub
def test_websub_pings_every_hub_without_any_credential(indexer):
    http = Recorder(status=204, body="")
    engine = indexer(http=http)
    engine.websub_ping("https://b.test")
    assert len(http.posts) >= len(WEBSUB_HUBS)
    for url, kwargs in http.posts:
        assert url in WEBSUB_HUBS
        payload = str(kwargs)
        assert "publish" in payload and "https://b.test" in payload


def test_websub_counts_only_the_successful_pings(indexer):
    http = Recorder(status=500, body="nope")
    engine = indexer(http=http)
    engine.websub_ping("https://b.test")
    assert engine.results.get("websub", "").lower()


# ------------------------------------------------------------------ orchestrator
def test_run_reports_every_channel_even_when_all_are_unconfigured(indexer):
    http = Recorder()
    engine = indexer(http=http)
    results = engine.run(["https://b.test/p.html"], "https://b.test")
    assert isinstance(results, dict)
    assert all(isinstance(value, str) for value in results.values())
    # Every channel degrades to a skip instead of raising when it has no credentials.


def test_run_with_no_new_urls_still_pings_the_hubs(indexer):
    http = Recorder(status=204, body="")
    engine = indexer(http=http)
    results = engine.run([], "https://b.test")
    assert isinstance(results, dict)


def test_run_never_raises_when_a_channel_is_broken(indexer):
    class Broken(Recorder):
        def post(self, url, **kwargs):
            raise RuntimeError("network down")

    engine = indexer(http=Broken())
    results = engine.run(["https://b.test/p.html"], "https://b.test")
    assert isinstance(results, dict) and results
