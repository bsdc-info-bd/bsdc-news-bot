import json

from bsdc_news.indexing import GoogleIndexer, Indexer
from bsdc_news.notify import Notifier
from bsdc_news.report import ItemOutcome, RunReport
from bsdc_news.social import SocialPoster, hashtags
from bsdc_news.state import State

from .conftest import FakeHttp, FakeResp


class Resp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


class FakeGoogle:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.sent = []

    def post(self, url, json=None, timeout=None):
        self.sent.append(json["url"])
        return Resp(self.statuses.pop(0) if self.statuses else 200)


def test_google_indexer_quota_and_permission_messages():
    g = GoogleIndexer(json.dumps({"type": "service_account", "client_email": "bot@p.iam.gserviceaccount.com"}))
    g._session = FakeGoogle([200, 429])
    ok, failed, fatal = g.publish(["u1", "u2", "u3"])
    assert ok == ["u1"] and failed == ["u2", "u3"] and "quota" in fatal
    g._session = FakeGoogle([403])
    ok, failed, fatal = g.publish(["u1"])
    assert "OWNER" in fatal and "bot@p.iam.gserviceaccount.com" in fatal


def test_indexer_queue_respects_daily_quota(settings, tmp_path):
    settings.secrets["indexing_service_account_json"] = json.dumps({"type": "service_account"})
    settings.data["indexing"]["google_daily_quota"] = 2
    state = State.load(tmp_path / "s.json")
    idx = Indexer(settings, FakeHttp(), state)
    idx.google._session = FakeGoogle([200, 200, 200])
    idx.google_submit(["a", "b", "c"])
    assert state.quota_used("google_indexing", "America/Los_Angeles") == 2
    assert state.data["indexing_queue"] == ["c"]  # waits for tomorrow's quota
    idx.google_submit([])
    assert "quota" in idx.results["google"]


def test_indexnow_only_with_verified_key(settings, tmp_path):
    state = State.load(tmp_path / "s.json")
    http = FakeHttp()
    idx = Indexer(settings, http, state)
    idx.indexnow_submit(["https://bsdcnews.blogspot.com/p.html"])
    assert idx.results["indexnow"].startswith("skipped")
    settings.secrets["indexnow_key"] = "a1b2c3d4e5f6"

    class KeyHttp(FakeHttp):
        def get(self, url, **kw):
            return FakeResp(200, "a1b2c3d4e5f6")

    http2 = KeyHttp()
    idx2 = Indexer(settings, http2, state)
    idx2.indexnow_submit(["https://bsdcnews.blogspot.com/p.html"])
    url, kwargs = http2.posts[-1]
    assert url == "https://api.indexnow.org/indexnow"
    assert kwargs["json"]["host"] == "bsdcnews.blogspot.com" and kwargs["json"]["key"] == "a1b2c3d4e5f6"


def test_websub_ping(settings, tmp_path):
    http = FakeHttp()
    idx = Indexer(settings, http, State.load(tmp_path / "s.json"))
    idx.websub_ping("https://bsdcnews.blogspot.com")
    assert any("pubsubhubbub" in u for u, _ in http.posts)
    assert idx.results["websub"].endswith("accepted")


def test_notifier_sends_summary_to_configured_channels(settings):
    settings.secrets.update({"telegram_bot_token": "123:abc", "telegram_chat_id": "42",
                             "discord_webhook_url": "https://discord.com/api/webhooks/x"})
    http = FakeHttp()
    n = Notifier(settings, http)
    report = RunReport()
    report.add(ItemOutcome("Title <b>", "https://src", "Src", "published", provider="gemini",
                           post_url="https://blog/p.html"))
    n.run_summary(report)
    urls = [u for u, _ in http.posts]
    assert any("api.telegram.org/bot123:abc/sendMessage" in u for u in urls)
    assert any("discord.com" in u for u in urls)
    tg = next(k for u, k in http.posts if "telegram" in u)["json"]["text"]
    assert "Title &lt;b&gt;" in tg and "https://blog/p.html" in tg


def test_social_poster_isolated_and_hashtags(settings):
    assert hashtags(["Tech News", "AI", "Nvidia", "Data Centers"]) == "#Ai #Nvidia #DataCenters"
    settings.secrets.update({"telegram_bot_token": "1:a", "telegram_channel_id": "@bsdc",
                             "mastodon_base_url": "https://mastodon.social", "mastodon_token": "t"})
    http = FakeHttp()
    poster = SocialPoster(settings, http)
    poster.share("Title", "https://blog/p.html", "Summary", ["AI"], image="https://img/x.jpg")
    assert set(poster.results) == {"telegram", "mastodon"}


def test_report_masks_secrets_when_saved(tmp_path):
    from bsdc_news.log import register_secret

    register_secret("SUPERSECRETAPIKEY123")
    r = RunReport()
    r.indexing["bing"] = "error: https://ssl.bing.com/x?apikey=SUPERSECRETAPIKEY123"
    path = r.save(tmp_path)
    assert "SUPERSECRETAPIKEY123" not in path.read_text() and "***" in path.read_text()


def test_report_markdown_contains_key_facts():
    r = RunReport(mode="live")
    r.add(ItemOutcome("A | B", "https://s", "Src", "published", provider="groq", post_url="https://p", quality=80,
                      words=700))
    r.add(ItemOutcome("C", "https://s2", "Src", "failed", reason="Blogger 500"))
    r.warnings.append("🔑 gemini: bad key")
    md = r.to_markdown()
    assert "A \\| B" in md and "groq" in md and "Blogger 500" in md and "bad key" in md
