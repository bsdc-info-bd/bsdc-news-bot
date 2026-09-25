"""``python -m bsdc_news doctor`` — live health check of every integration.

Prints ✅/⚠️/❌ per check with a concrete fix, and exits non-zero only when
publishing is impossible (Blogger broken or config invalid)."""

from __future__ import annotations

import json

from .errors import BotError, ConfigError
from .http import HttpClient
from .log import get_logger
from .settings import Settings
from .writer import GenerationRequest, build_writer

log = get_logger("doctor")


class Checks:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.rows.append(("✅", name, detail))
        log.info("✅ %-28s %s", name, detail)

    def warn(self, name: str, detail: str) -> None:
        self.rows.append(("⚠️", name, detail))
        log.warning("⚠️ %-28s %s", name, detail)

    def fail(self, name: str, detail: str) -> None:
        self.rows.append(("❌", name, detail))
        log.error("❌ %-28s %s", name, detail)

    @property
    def failed(self) -> bool:
        return any(r[0] == "❌" for r in self.rows)


def run_doctor(settings: Settings, deep: bool = True) -> int:
    c = Checks()
    blocking = False

    # 1. configuration
    try:
        for w in settings.validate(require_publish=True):
            c.warn("configuration", w)
        c.ok("configuration", f"{len([f for f in settings.feeds if f.enabled])} feeds enabled")
    except ConfigError as exc:
        c.fail("configuration", str(exc).replace("\n", " "))
        blocking = True

    # 2. Blogger
    if deep and settings.secret("google_refresh_token"):
        from .blogger import BloggerClient

        try:
            client = BloggerClient(settings.secret("blog_id"), settings.secret("google_client_id"),
                                   settings.secret("google_client_secret"), settings.secret("google_refresh_token"))
            info = client.get_blog()
            posts = client.recent_posts(10)
            c.ok("Blogger API", f"'{info.get('name')}' {info.get('url')} — {len(posts)} recent posts readable")
        except BotError as exc:
            c.fail("Blogger API", exc.describe().replace("\n", " "))
            blocking = True

    # 3. The writer: a local engine, so this is a self-test rather than a key check

    writer = build_writer(settings)
    health = writer.health()
    c.ok("Writer engine", f"{health['engine']} — no API key required "
                          f"({health['gazetteer_entries']} gazetteer entries loaded)")
    if not writer.enabled:
        c.warn("Writer enabled", "writer.enabled is false — extractive briefs will be used")
    if deep:
        sample = ("The bsdc news doctor verifies the writing engine offline. "
                  "It extracted 12 facts from a 400-word report published on Monday. "
                  'The chief executive said the platform ships in October at $99. '
                  '"We rebuilt the pipeline around local analysis," she told reporters. '
                  "Analysts said the price cut will pressure rivals in Bangladesh. ") * 3
        try:
            draft = writer.generate(GenerationRequest(
                title="Doctor self-test: engine writes an article offline",
                text=sample, source="bsdc news doctor", url="https://example.com/doctor",
                target_words=180, min_words=60, category="Technology"))
            if draft is None:
                c.fail("Writer self-test", "engine declined a valid sample article")
                blocking = True
            else:
                c.ok("Writer self-test", f"{draft.words} words, quality {draft.quality_score}/100, "
                                         f"confidence {draft.confidence:.2f}, "
                                         f"{draft.timings.get('total', 0):.2f}s")
        except Exception as exc:                       # noqa: BLE001 - report anything
            c.fail("Writer self-test", f"{type(exc).__name__}: {exc}"[:220])
            blocking = True

    # 4. Indexing
    sa = settings.secret("indexing_service_account_json")
    if sa:
        try:
            info = json.loads(sa)
            c.ok("Indexing service account", f"{info.get('client_email', '?')} (must be Owner in Search Console)")
        except ValueError:
            c.warn("Indexing service account", "INDEXING_SERVICE_ACCOUNT_JSON is not valid JSON")
    else:
        c.warn("Google Indexing API", "not configured (optional)")
    if settings.secret("indexnow_key"):
        c.ok("IndexNow key", "configured — key file must be reachable on your domain (see docs/SEO.md)")

    # 5. Feeds
    if deep:
        from .feeds import FeedFetcher

        results = FeedFetcher(HttpClient()).fetch_all(settings.feeds)
        bad = [r for r in results if r.error]
        (c.ok if not bad else c.warn)("RSS feeds", f"{len(results) - len(bad)}/{len(results)} working"
                                      + (f" — broken: {', '.join((r.feed.name or r.feed.url) for r in bad[:6])}"
                                         if bad else ""))

    # 6. Optional integrations
    optional = {
        "Telegram notifications": settings.secret("telegram_bot_token") and settings.secret("telegram_chat_id"),
        "Discord notifications": settings.secret("discord_webhook_url"),
        "Telegram channel auto-post": settings.secret("telegram_channel_id"),
        "Facebook Page auto-post": settings.secret("facebook_page_token"),
        "Mastodon auto-post": settings.secret("mastodon_token"),
        "Bluesky auto-post": settings.secret("bluesky_app_password"),
    }
    enabled = [k for k, v in optional.items() if v]
    c.ok("Optional integrations", ", ".join(enabled) if enabled else "none configured (all optional)")

    log.info("-" * 60)
    if blocking:
        log.error("Publishing is NOT possible until the ❌ items above are fixed.")
        return 1
    if c.failed:
        log.warning("Publishing works, but some integrations need attention (see ❌/⚠️ above).")
    else:
        log.info("All essential checks passed. 🎉")
    return 0
