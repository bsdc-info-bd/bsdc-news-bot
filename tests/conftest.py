"""Shared fixtures and fakes: the whole pipeline runs offline in tests."""

from __future__ import annotations

import sys
from email.utils import format_datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bsdc_news.http import SimpleResponse  # noqa: E402
from bsdc_news.settings import load_settings  # noqa: E402
from bsdc_news.utils import utcnow  # noqa: E402
from bsdc_news.writer import ArticleDraft  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

# 1x1 is too small; build a valid 1600x900 PNG header for dimension sniffing
PNG_1600x900 = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1600).to_bytes(4, "big") +
                (900).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00" + b"\x00" * 64)


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def feed_xml() -> str:
    return load_fixture("feed.xml").replace("{RECENT}", format_datetime(utcnow()))


class FakeResp:
    def __init__(self, status=200, text="", content=None, headers=None, url=""):
        self.status_code = status
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = headers or {}
        self.url = url

    def json(self):
        import json

        return json.loads(self.text)

    def iter_content(self, _n):
        yield self.content

    def close(self):
        pass


class FakeHttp:
    """Implements the subset of HttpClient used by the pipeline."""

    def __init__(self, pages: dict[str, str] | None = None, feed: str | None = None):
        self.pages = pages or {}
        self.feed = feed if feed is not None else feed_xml()
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[str] = []

    def allowed(self, url):
        return True

    def get(self, url, **kwargs):
        self.gets.append(url)
        if "trends.google" in url:
            return FakeResp(200, "<rss><channel><item><title>nvidia</title></item></channel></rss>")
        if url.endswith(".xml") or "feed" in url or url.endswith(".atom"):
            return FakeResp(200, self.feed, headers={"ETag": "abc"})
        return FakeResp(404, "")

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResp(200, "{}")

    def fetch_html(self, url, timeout=None):
        for key, html in self.pages.items():
            if key in url:
                return SimpleResponse(200, html, html.encode(), {"Content-Type": "text/html"}, url)
        return SimpleResponse(404, "", b"", {}, url)

    def get_bytes(self, url, limit=65536, timeout=10.0):
        if "avatar" in url or "ads." in url:
            return 404, {}, b""
        return 200, {"Content-Type": "image/png"}, PNG_1600x900


class FakeBlogger:
    def __init__(self, existing=None, fail_insert=None):
        self.existing = existing or []
        self.inserted = []
        self.patched = []
        self.fail_insert = fail_insert

    def get_blog(self):
        return {"name": "bsdc news", "url": "https://bsdcnews.blogspot.com"}

    def recent_posts(self, limit=150):
        return list(self.existing)

    def insert(self, title, content, labels, *, draft=False, publish_at=None, search_description=""):
        from bsdc_news.blogger import PublishedPost

        if self.fail_insert:
            raise self.fail_insert
        pid = str(len(self.inserted) + 1)
        url = f"https://bsdcnews.blogspot.com/2026/09/post-{pid}.html"
        self.inserted.append({"id": pid, "title": title, "content": content, "labels": labels, "draft": draft,
                              "publish_at": publish_at, "search_description": search_description, "url": url})
        return PublishedPost(pid, url, "DRAFT" if draft else "LIVE", title)

    def update_content(self, post_id, content):
        self.patched.append((post_id, content))


def good_body(words: int = 620) -> str:
    sentences = [
        "Nvidia introduced a new data-center accelerator called Rubin Ultra during a keynote in San Jose.",
        "The company says the design doubles performance per watt compared with its previous flagship.",
        "Rubin Ultra includes 288 gigabytes of high-bandwidth memory for the largest AI models.",
        "Shipments to cloud providers are planned for the first quarter of 2027.",
        "Analysts expect strong demand from hyperscale cloud companies and national AI programs.",
        "Rivals including AMD and Intel are racing to close the gap in accelerator sales.",
        "Energy consumption remains a concern for regulators in several US states.",
        "Nvidia argues that efficient chips let operators do more work within existing power limits.",
    ]
    paras, count, i = [], 0, 0
    while count < words:
        para = " ".join(sentences[(i + k) % len(sentences)] for k in range(3))
        paras.append(f"<p>{para}</p>")
        count += len(para.split())
        i += 1
    body = paras[0]
    sections = ["Key Details", "Background", "Why It Matters", "What's Next"]
    per = max(1, (len(paras) - 1) // len(sections))
    for idx, name in enumerate(sections):
        chunk = paras[1 + idx * per: 1 + (idx + 1) * per]
        body += f"<h2>{name}</h2>" + "".join(chunk)
    body += "<ul><li>Twice the performance per watt</li><li>Ships in early 2027</li></ul>"
    return body


class FakeRouter:
    """AI router double returning a fixed draft (or None to simulate outage)."""

    def __init__(self, draft: ArticleDraft | None = "default", auth_errors=None):
        if draft == "default":
            draft = ArticleDraft(headline="Nvidia Unveils Rubin Ultra Chip With Double the Efficiency",
                                 body_html=good_body(), meta_description="Nvidia's Rubin Ultra accelerator doubles "
                                 "performance per watt and ships to cloud providers in early 2027, the company said.",
                                 category="AI", tags=["Nvidia", "AI chips"], key_points=["Doubles efficiency"],
                                 faq=[{"q": "When does Rubin Ultra ship?", "a": "In the first quarter of 2027."},
                                      {"q": "Who makes it?", "a": "Nvidia."}], provider="fake", model="fake-1")
        self.draft = draft
        self.auth_errors = auth_errors or {}
        self.calls = 0
        self.enabled = True

    def generate(self, req):
        self.calls += 1
        return self.draft

    def health(self):
        return {"engine": "fake-writer", "enabled": self.enabled, "requires_api_key": False,
                "auth_errors": self.auth_errors, "calls": self.calls, "articles": self.calls,
                "cost": "free", "usage": {}}

    def describe(self, draft):
        return f"{getattr(draft, 'words', 0)} words (fake writer)"

    def plan_seo(self, draft, **kwargs):
        """The real planner, so tests exercise the SEO layer end to end."""
        try:
            from bsdc_news.seo import planner as seo_planner

            return seo_planner.plan(draft.as_cortex(), site_name="bsdc news",
                                    site_url="https://bsdc-news.blogspot.com",
                                    category=kwargs.get("category", ""),
                                    related_posts=kwargs.get("related_posts") or [])
        except Exception:                                # noqa: BLE001 - keep tests focused
            return None


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for var in ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT"):
        monkeypatch.delenv(var, raising=False)
    s = load_settings(env={"BLOG_ID": "1234567890", "GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": "csecret",
                           "GOOGLE_REFRESH_TOKEN": "rtoken-abcdef"}, offline=True)
    s.root = tmp_path
    s.data["state"]["path"] = str(tmp_path / "state.json")
    s.data["report"]["dir"] = str(tmp_path / "reports")
    s.data["report"]["dashboard"] = str(tmp_path / "public" / "index.html")
    s.data["publishing"]["sleep_between_posts"] = 0
    s.data["publishing"]["spread_evenly"] = False  # keep tests independent of the time of day
    s.data["publishing"]["max_posts_per_run"] = 4   # keep tests independent of the shipped config value
    s.data["images"]["openverse_fallback"] = False
    s.data["ranking"]["trends_geo"] = []
    from bsdc_news.settings import Feed

    s.feeds = [Feed(url="https://example-tech.com/feed.xml", name="Example Tech", category="Technology")]
    return s


@pytest.fixture
def article_html():
    return load_fixture("article.html")
