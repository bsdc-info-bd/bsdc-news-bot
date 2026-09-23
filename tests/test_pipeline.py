"""End-to-end pipeline tests with fake network, Blogger and AI."""

import json

from bsdc_news.errors import AuthError
from bsdc_news.pipeline import EXIT_CONFIG, EXIT_FAILED, EXIT_OK, Pipeline
from bsdc_news.state import State

from .conftest import FakeBlogger, FakeHttp, FakeRouter, load_fixture

ARTICLE_KEY = "nvidia-rubin-ultra"


def make(settings, *, router=None, blogger=None, pages=None, http=None):
    http = http or FakeHttp(pages if pages is not None else {ARTICLE_KEY: load_fixture("article.html")})
    blogger = blogger or FakeBlogger()
    state = State.load(settings.path(settings.get("state.path")))
    return Pipeline(settings, blogger=blogger, http=http, state=state,
                    ai_router=router if router is not None else FakeRouter()), blogger, http


def test_happy_path_publishes_with_ai(settings):
    pipe, blogger, _ = make(settings)
    report = pipe.run()
    assert report.exit_code == EXIT_OK, report.fatal_errors
    assert len(blogger.inserted) == 1
    post = blogger.inserted[0]
    assert post["title"] == "Nvidia Unveils Rubin Ultra Chip With Double the Efficiency"
    assert "Tech News" in post["labels"] and "AI" in post["labels"]
    assert post["search_description"].startswith("Nvidia's Rubin Ultra")
    assert '"@context":"https://schema.org"' in post["content"]
    assert blogger.patched and post["url"] in blogger.patched[0][1]  # self-referencing second pass
    # the deals item, the old item and the item without an article page are not published
    statuses = {o.title[:15]: o.status for o in report.outcomes}
    assert statuses.get("Hackers exploit") == "skipped"
    assert report.filtered.get("blocked keyword", 0) + report.filtered.get("low-value headline (deals/listicle/puzzle)", 0) >= 1


def test_second_run_does_not_republish(settings):
    pipe, blogger, http = make(settings)
    assert pipe.run().exit_code == EXIT_OK
    pipe2, blogger2, _ = make(settings, http=http)
    report2 = pipe2.run()
    assert blogger2.inserted == []
    assert report2.filtered.get("already published", 0) >= 1
    # nothing new to try → not a failure
    assert report2.exit_code == EXIT_OK


def test_existing_blog_title_is_skipped(settings):
    existing = [{"title": "Nvidia unveils Rubin Ultra AI chip with 2x efficiency",
                 "url": "https://bsdcnews.blogspot.com/2026/09/x.html"}]
    pipe, blogger, _ = make(settings, blogger=FakeBlogger(existing=existing))
    pipe.run()
    assert blogger.inserted == []


def test_ai_outage_falls_back_to_brief(settings):
    pipe, blogger, _ = make(settings, router=FakeRouter(draft=None))
    report = pipe.run()
    assert report.exit_code == EXIT_OK, report.fatal_errors
    assert len(blogger.inserted) == 1
    assert "Example Tech reports" in blogger.inserted[0]["content"]
    assert "written with the help of AI" not in blogger.inserted[0]["content"]
    assert report.outcomes[0].provider == "brief" or any(o.provider == "brief" for o in report.outcomes)


def test_ai_outage_draft_mode_saves_drafts(settings):
    settings.data["publishing"]["ai_failure_mode"] = "draft"
    pipe, blogger, _ = make(settings, router=FakeRouter(draft=None))
    pipe.run()
    assert blogger.inserted and blogger.inserted[0]["draft"] is True


def test_ai_outage_skip_mode_fails_the_run_loudly(settings):
    settings.data["publishing"]["ai_failure_mode"] = "skip"
    pipe, blogger, _ = make(settings, router=FakeRouter(draft=None))
    report = pipe.run()
    assert blogger.inserted == []
    assert report.exit_code == EXIT_FAILED  # no more fake green "success"
    assert report.fatal_errors


def test_blogger_auth_error_stops_run_with_failure(settings):
    blogger = FakeBlogger(fail_insert=AuthError("unauthorized", hint="refresh token"))
    pipe, _, _ = make(settings, blogger=blogger)
    report = pipe.run()
    assert report.exit_code == EXIT_FAILED
    assert "refresh token" in report.fatal_errors[0]


def test_missing_secrets_is_config_error(settings):
    settings.secrets["blog_id"] = ""
    pipe, blogger, _ = make(settings)
    report = pipe.run()
    assert report.exit_code == EXIT_CONFIG and "BLOG_ID" in report.fatal_errors[0]


def test_daily_limit_and_budget(settings):
    settings.data["publishing"]["max_posts_per_day"] = 0
    pipe, blogger, _ = make(settings)
    report = pipe.run()
    assert blogger.inserted == [] and report.exit_code == EXIT_OK


def test_reports_state_and_dashboard_written(settings, tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    output = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    pipe, blogger, _ = make(settings)
    pipe.run()
    state = json.loads((tmp_path / "state.json").read_text())
    assert len(state["published"]) == 1 and state["runs"]["consecutive_failures"] == 0
    assert (tmp_path / "reports" / "latest.json").exists()
    assert "Smart Publisher" in (tmp_path / "public" / "index.html").read_text()
    md = summary.read_text()
    assert "Published" in md and "Nvidia" in md
    assert "published=1" in output.read_text()


def test_dry_run_uses_fake_blogger_and_needs_no_secrets(settings):
    settings.dry_run = True
    for k in list(settings.secrets):
        settings.secrets[k] = ""
    state = State.load(settings.path(settings.get("state.path")))
    pipe = Pipeline(settings, http=FakeHttp({ARTICLE_KEY: load_fixture("article.html")}), state=state,
                    ai_router=FakeRouter())
    report = pipe.run()
    assert report.exit_code == EXIT_OK, report.fatal_errors
    assert report.count("dry-run") == 1
    assert pipe.blogger.inserted[0]["url"].startswith("https://example.blogspot.com/")


def test_brief_posts_get_brief_label(settings):
    pipe, blogger, _ = make(settings, router=FakeRouter(draft=None))
    pipe.run()
    assert "News Brief" in blogger.inserted[0]["labels"]


def test_low_quality_ai_draft_is_retried_with_feedback_then_briefed(settings):
    from bsdc_news.ai.base import ArticleDraft

    class Router(FakeRouter):
        def __init__(self):
            super().__init__(ArticleDraft(headline="Bad", body_html="<p>Too short.</p>", provider="fake", model="m"))
            self.feedback = []

        def generate(self, req):
            self.feedback.append(req.feedback)
            return super().generate(req)

    router = Router()
    pipe, blogger, _ = make(settings, router=router)
    report = pipe.run()
    assert router.calls == 2 and router.feedback[0] == "" and "too short" in router.feedback[1]
    assert report.exit_code == EXIT_OK and "Example Tech reports" in blogger.inserted[0]["content"]


def test_ai_auth_error_turns_run_red_once_per_day(settings):
    router = FakeRouter(draft=None, auth_errors={"gemini": "401 for every model"})
    pipe, blogger, _ = make(settings, router=router)
    report = pipe.run()
    assert blogger.inserted, "posts still go out with the fallback writer"
    assert report.exit_code == EXIT_FAILED and "AI key rejected" in report.fatal_errors[0]
    # second run within 24h: stays green (no alert spam), still publishes nothing new but no failure
    pipe2, _, _ = make(settings, router=FakeRouter(draft=None, auth_errors={"gemini": "401"}))
    assert pipe2.run().exit_code == EXIT_OK


def test_state_is_rebuilt_from_blog_when_lost(settings):
    class Blogger(FakeBlogger):
        def recent_source_links(self, limit=60):
            return [("https://example-tech.com/2026/09/22/nvidia-rubin-ultra/?utm_source=x", "AI-rewritten title")]

    pipe, blogger, _ = make(settings, blogger=Blogger())
    report = pipe.run()
    assert blogger.inserted == []  # the story was already on the blog under a different title
    assert report.filtered.get("already published", 0) >= 1


def test_dry_run_never_writes_state(settings):
    settings.dry_run = True
    state = State.load(settings.path(settings.get("state.path")))
    pipe = Pipeline(settings, http=FakeHttp({ARTICLE_KEY: load_fixture("article.html")}), state=state,
                    ai_router=FakeRouter())
    assert pipe.run().count("dry-run") == 1
    assert not settings.path(settings.get("state.path")).exists()


def test_brief_uses_each_sentence_once(article_html):
    from bsdc_news.brief import build_brief
    from bsdc_news.extractor import parse_article

    art = parse_article(article_html, "https://example-tech.com/x")
    body = build_brief("Nvidia unveils Rubin Ultra", art.text, "Example Tech", "https://example-tech.com/x").body_html
    import re as _re

    fragments = [f.strip() for f in _re.split(r"<[^>]+>", body) if len(f.strip()) > 40]
    assert len(fragments) == len(set(fragments))


def test_dotenv_loader(tmp_path, monkeypatch):
    from bsdc_news.cli import load_dotenv

    env = tmp_path / ".env"
    env.write_text('# comment\nexport BSDC_TEST_A="quoted value"\nBSDC_TEST_B=plain\nBSDC_TEST_C=keep\n')
    monkeypatch.setenv("BSDC_TEST_C", "from-env")
    monkeypatch.delenv("BSDC_TEST_A", raising=False)
    monkeypatch.delenv("BSDC_TEST_B", raising=False)
    assert load_dotenv(env) == 2
    import os

    assert os.environ["BSDC_TEST_A"] == "quoted value" and os.environ["BSDC_TEST_B"] == "plain"
    assert os.environ["BSDC_TEST_C"] == "from-env"
