"""The publishing pipeline (one run = one call to :meth:`Pipeline.run`).

Stages: validate → connect Blogger → rebuild state if needed → fetch feeds →
filter/dedupe/rank → for each candidate: extract → images → AI write (with
quality gate + one feedback retry) or brief fallback → render → publish →
share → index → report/state/dashboard → notify → exit code.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta

from .ai import build_router
from .ai.base import ArticleDraft, GenerationRequest, load_prompt_template
from .blogger import BloggerClient, DryRunBlogger, ExistingIndex, schedule_times
from .brief import build_brief
from .content.quality import assess
from .content.render import RenderInput, build_post_html
from .content.sanitize import sanitize_html, strip_markdown
from .content.seo import clean_headline, meta_description
from .content.taxonomy import Taxonomy
from .dedupe import is_near_duplicate, title_fingerprint
from .errors import AuthError, BotError, ConfigError, ExtractionError, PublishError, WriterUnavailable
from .extractor import Article, Extractor, ImageCandidate
from .feeds import FeedFetcher, FeedItem
from .filters import ItemFilter
from .http import HttpClient
from .images import ImagePicker
from .indexing import Indexer
from .log import get_logger, group
from .notify import Notifier
from .ranking import Ranker, diversify
from .report import ItemOutcome, RunReport, build_dashboard
from .settings import Settings
from .social import SocialPoster
from .state import State
from .trends import fetch_trending_terms
from .utils import Stopwatch, canonical_url, in_time_window, iso, paced_allowance, parse_iso, utcnow

log = get_logger("pipeline")

EXIT_OK, EXIT_FAILED, EXIT_CONFIG = 0, 1, 2


@dataclass
class Prepared:
    item: FeedItem
    article: Article
    draft: ArticleDraft
    quality: int
    words: int
    category: str
    labels: list[str]
    images: list[tuple[ImageCandidate, str]]
    headline: str
    meta: str
    publish_as_draft: bool = False
    issues: tuple[str, ...] = ()


class Pipeline:
    def __init__(self, settings: Settings, *, blogger=None, http: HttpClient | None = None,
                 state: State | None = None, ai_router=None, fetcher=None) -> None:
        self.s = settings
        self.http = http or HttpClient(timeout=float(settings.get("extraction.timeout", 20)),
                                       retries=int(settings.get("http.retries", 2)),
                                       per_host_interval=float(settings.get("http.per_host_interval", 0.8)),
                                       respect_robots=bool(settings.get("extraction.respect_robots", True)))
        self.state = state or State.load(settings.path(settings.get("state.path", "data/state.json")))
        if settings.dry_run:
            self.state.readonly = True
        self.report = RunReport(mode="dry-run" if settings.dry_run else settings.get("publishing.mode", "live"))
        self.blogger = blogger
        self.ai = ai_router if ai_router is not None else build_router(settings, self.state)
        self.fetcher = fetcher or FeedFetcher(self.http)
        self.extractor = Extractor(self.http, settings)
        self.images = ImagePicker(self.http, settings)
        self.filter = ItemFilter(settings)
        self.taxonomy = Taxonomy(settings)
        self.notifier = Notifier(settings, self.http)
        self.social = SocialPoster(settings, self.http)
        self.prompt_template = load_prompt_template(settings.get("ai.prompt_file", ""))
        self.site_url = settings.get("site.url", "")
        self.source_links: set[str] = set()

    # ───────────────────────── helpers ─────────────────────────
    def _warn(self, message: str) -> None:
        self.report.warnings.append(message)
        log.warning(message)

    def _connect_blogger(self) -> None:
        if self.blogger is not None:
            return
        if self.s.dry_run:
            reader = None
            if all(self.s.secret(k) for k in ("blog_id", "google_client_id", "google_client_secret",
                                               "google_refresh_token")):
                reader = BloggerClient(self.s.secret("blog_id"), self.s.secret("google_client_id"),
                                       self.s.secret("google_client_secret"), self.s.secret("google_refresh_token"))
            self.blogger = DryRunBlogger(self.site_url or "https://example.blogspot.com", reader=reader)
            return
        self.blogger = BloggerClient(self.s.secret("blog_id"), self.s.secret("google_client_id"),
                                     self.s.secret("google_client_secret"), self.s.secret("google_refresh_token"))

    def _budget(self) -> int:
        pub = self.s.data["publishing"]
        per_run = int(pub["max_posts_per_run"])
        tz = self.s.get("site.timezone", "UTC")
        per_day = int(pub["max_posts_per_day"])
        used = self.state.quota_used("posts", tz)
        left_today = per_day - used
        budget = max(0, min(per_run, left_today))
        if pub.get("spread_evenly", True) and left_today > 0:
            paced = paced_allowance(per_day, tz, utcnow()) - used
            if paced < budget:
                log.info("⏱️ Pacing: %d/%d posts used today — %d allowed this run to spread posts evenly",
                         used, per_day, max(0, paced))
            budget = max(0, min(budget, paced))
        if pub.get("quiet_hours") and in_time_window(pub["quiet_hours"], tz):
            budget = min(budget, int(pub.get("quiet_hours_max_posts", 1)))
            log.info("🌙 Quiet hours (%s %s) — max %d post(s) this run", pub["quiet_hours"], tz, budget)
        if left_today <= 0:
            log.info("📅 Daily post limit (%s) reached", pub["max_posts_per_day"])
        return budget

    def _rebuild_state_if_needed(self) -> None:
        """If the state file was lost, recover the source links of recent posts from the blog
        itself so stories re-titled by the AI are never published twice."""
        if self.state.data["published"] or self.state.data["meta"].get("rebuilt_from_blog"):
            return
        getter = getattr(self.blogger, "recent_source_links", None)
        if not getter:
            return
        try:
            links = getter(60)
        except BotError as exc:
            log.debug("State rebuild skipped: %s", exc)
            return
        for src, title in links:
            self.source_links.add(canonical_url(src))
            self.state.mark_published(src, {"title": title, "post_url": "", "source": "recovered"},
                                      fingerprint=title_fingerprint(title))
        self.state.data["meta"]["rebuilt_from_blog"] = iso()
        if links:
            log.info("   ♻️ State rebuilt from %d recent blog posts", len(links))

    # ───────────────────────── stages ─────────────────────────
    def collect(self) -> list[FeedItem]:
        with group("📡 Fetching feeds"):
            results = self.fetcher.fetch_all(self.s.feeds)
        items: list[FeedItem] = []
        for res in results:
            if res.error:
                self.report.feeds_failed.append(f"{res.feed.name or res.feed.url}: {res.error}")
            else:
                self.report.feeds_ok += 1
            items.extend(res.items)
        if not items and results and all(r.error for r in results):
            raise BotError("All feeds failed — network problem or every feed URL is broken",
                           hint="Run `python -m bsdc_news feeds` to test each feed")
        return items

    def select(self, items: list[FeedItem], existing: ExistingIndex) -> list[FeedItem]:
        fresh: list[FeedItem] = []
        seen_canon: set[str] = set()
        retry_h = float(self.s.get("state.failed_retry_hours", 12))
        max_attempts = int(self.s.get("state.max_failed_attempts", 2))
        for it in items:
            canon = it.canonical
            if canon in seen_canon:
                continue
            seen_canon.add(canon)
            decision = self.filter.check(it)
            if not decision.ok:
                self.report.filtered_inc(decision.reason)
                continue
            fp = title_fingerprint(it.title)
            if self.state.is_published(it.url) or canon in existing.canonical or canon in self.source_links:
                self.report.filtered_inc("already published")
                continue
            if it.title.strip().lower() in existing.titles or fp in existing.fingerprints or self.state.title_seen(fp):
                self.report.filtered_inc("same headline already on blog")
                continue
            if self.state.should_skip_failed(it.url, retry_h, max_attempts):
                self.report.filtered_inc("failed recently (back-off)")
                continue
            fresh.append(it)

        trending: list[str] = []
        if not self.s.offline and self.s.get("ranking.trends_geo"):
            with group("📈 Trends"):
                trending = fetch_trending_terms(self.http, self.s.get("ranking.trends_geo", []))
        ranked = Ranker(self.s, trending).rank(fresh)
        # Similar story already covered recently? (fuzzy match against blog + state titles)
        recent_titles = [p.get("title", "") for p in existing.posts[:120]] + \
                        [r.get("title", "") for r in self.state.published_records()[:200]]
        out = []
        for it in ranked:
            if is_near_duplicate(it.title, recent_titles, threshold=0.62):
                self.report.filtered_inc("similar story already covered")
                continue
            out.append(it)
        self.report.candidates = len(out)
        pub = self.s.data["publishing"]
        limit = int(self.s.get("ranking.candidates_to_try", 20))
        return diversify(out, int(pub["max_per_source_per_run"]) + 1, int(pub["max_per_category_per_run"]) + 2, limit)

    def _write(self, item: FeedItem, article: Article, category: str) -> tuple[ArticleDraft, int, int, bool, tuple]:
        """AI draft with quality gate (+1 retry with editor feedback), else extractive brief."""
        req = GenerationRequest(
            title=item.title, text=article.text, source=item.source, url=item.url,
            published=article.published or (iso(item.published) if item.published else ""),
            related=item.related_sources, categories=list(self.taxonomy.categories), site=self.s.site_name,
            target_words=int(self.s.get("ai.target_words", 750)), min_words=int(self.s.get("ai.min_words", 450)),
            max_source_chars=int(self.s.get("ai.max_source_chars", 12000)),
            temperature=float(self.s.get("ai.temperature", 0.6)),
            max_output_tokens=int(self.s.get("ai.max_output_tokens", 8192)), prompt_template=self.prompt_template,
        )
        min_score = int(self.s.get("publishing.min_quality_score", 55))
        if self.ai.enabled:
            for attempt in range(2):
                draft = self.ai.generate(req)
                if draft is None:
                    break
                draft.body_html = sanitize_html(strip_markdown(draft.body_html), allow_links=False)
                quality = assess(draft.body_html, article.text, min_words=req.min_words,
                                 target_words=req.target_words, min_score=min_score)
                if quality.passed:
                    return draft, quality.score, quality.words, False, tuple(quality.issues)
                log.info("   🧪 Quality %d/100 < %d (%s) — %s", quality.score, min_score,
                         "; ".join(quality.issues[:3]), "asking for a revision" if attempt == 0 else "using brief")
                req.feedback = "; ".join(quality.issues[:5])

        mode = self.s.get("publishing.ai_failure_mode", "brief")
        if mode == "skip":
            raise WriterUnavailable("AI unavailable and ai_failure_mode=skip")
        draft = build_brief(item.title, article.text, item.source, item.url,
                            description=article.description or item.summary, category=category,
                            tags=article.keywords[:5], related=item.related_sources)
        draft.body_html = sanitize_html(draft.body_html, allow_links=True)
        quality = assess(draft.body_html, article.text, min_score=min_score, ai_generated=False)
        if not quality.passed:
            raise ExtractionError(f"brief quality too low ({quality.score}: {'; '.join(quality.issues[:2])})")
        return draft, quality.score, quality.words, mode == "draft", tuple(quality.issues)

    def prepare(self, item: FeedItem, existing: ExistingIndex) -> Prepared:
        article = self.extractor.extract(item.url)
        min_words = int(self.s.get("extraction.min_words", 180))
        if article.words < min_words:
            raise ExtractionError(f"only {article.words} words extracted (< {min_words})",
                                  permanent=article.words < 60)
        if article.paywalled and article.words < min_words * 2:
            raise ExtractionError("paywalled article", permanent=True)

        category = self.taxonomy.classify(item.title, article.text, item.category)
        images = self.images.select(article.images, feed_image=item.image)
        if not images:
            images = self.images.openverse(" ".join(item.title.split()[:6]))
        if not images and self.s.get("publishing.require_image", True):
            raise ExtractionError("no usable image (article + open-licence fallback)")
        rendered_images = [(c, self.images.display_url(c)) for c in images[:2]]

        draft, score, words, as_draft, issues = self._write(item, article, category)

        headline = clean_headline(draft.headline or item.title) or clean_headline(item.title)
        if draft.ai_generated and is_near_duplicate(headline, list(existing.titles), 0.9):
            headline = clean_headline(item.title)
        meta = meta_description(draft.meta_description, article.description or item.summary or article.text)
        if draft.category in self.taxonomy.categories:
            category = draft.category
        labels = self.taxonomy.labels(headline, article.text, category, draft.tags, item.source)
        brief_label = self.s.get("publishing.brief_label", "")
        if not draft.ai_generated and brief_label and brief_label not in labels:
            labels = (labels[: max(1, int(self.s.get("publishing.labels_max", 6)) - 1)] + [brief_label])
        return Prepared(item=item, article=article, draft=draft, quality=score, words=words, category=category,
                        labels=labels, images=rendered_images, headline=headline, meta=meta,
                        publish_as_draft=as_draft, issues=issues)

    def publish(self, prep: Prepared, existing: ExistingIndex, publish_at=None) -> tuple[str, str]:
        inp = RenderInput(
            headline=prep.headline, body_html=prep.draft.body_html, meta_description=prep.meta,
            category=prep.category, labels=prep.labels, source_name=prep.item.source, source_url=prep.item.url,
            words=prep.words, images=prep.images, key_points=prep.draft.key_points, faq=prep.draft.faq,
            related_posts=[p for p in existing.recent(8) if p["title"] != prep.headline][:4],
            related_sources=prep.item.related_sources, ai_generated=prep.draft.ai_generated,
            published_iso=iso(publish_at) if publish_at else iso(),
            original_author=prep.article.author if len(prep.article.author) < 60 else "",
        )
        draft_mode = prep.publish_as_draft or self.s.get("publishing.mode", "live") == "draft"
        post = self.blogger.insert(prep.headline, build_post_html(inp, self.s), prep.labels, draft=draft_mode,
                                   publish_at=publish_at, search_description=prep.meta)
        if post.url and not draft_mode:
            try:  # second pass: self-referencing schema URL + share buttons with the real post URL
                self.blogger.update_content(post.post_id, build_post_html(inp, self.s, post_url=post.url))
            except (PublishError, AuthError) as exc:
                log.debug("Post patch skipped: %s", exc)
        return post.url, post.status

    # ───────────────────────── main ─────────────────────────
    def run(self) -> RunReport:
        clock = Stopwatch()
        report = self.report
        try:
            self._run(report)
        except ConfigError as exc:
            report.fatal_errors.append(exc.describe())
            report.exit_code = EXIT_CONFIG
            log.error("❌ Configuration error:\n%s", exc.describe())
        except AuthError as exc:
            report.fatal_errors.append(exc.describe())
            report.exit_code = EXIT_FAILED
            log.error("🔑 %s", exc.describe())
        except BotError as exc:
            report.fatal_errors.append(exc.describe())
            report.exit_code = EXIT_FAILED
            log.error("❌ %s", exc.describe())
        except Exception as exc:  # truly unexpected: record and fail loudly
            log.exception("💥 Unexpected crash: %s", exc)
            report.fatal_errors.append(f"Unexpected {type(exc).__name__}: {exc}")
            report.exit_code = EXIT_FAILED
        finally:
            report.duration_s = clock.elapsed
            report.finished = iso()
            report.ai = self.ai.health() if self.ai else {}
            self._finish(report)
        return report

    def _run(self, report: RunReport) -> None:
        for w in self.s.validate(require_publish=not self.s.dry_run):
            self._warn(w)
        self.state.prune(int(self.s.get("state.retention_days", 30)))

        self._connect_blogger()
        with group("📝 Connecting to Blogger"):
            info = self.blogger.get_blog()
            self.site_url = self.site_url or info.get("url", "")
            if self.site_url and not self.s.get("site.url"):
                self.s.data["site"]["url"] = self.site_url
            self.state.data["blog"] = {"url": self.site_url, "name": info.get("name", "")}
            existing = ExistingIndex(self.blogger.recent_posts(150))
            self._rebuild_state_if_needed()
            log.info("   Blog: %s (%s) — %d recent posts indexed for de-duplication",
                     info.get("name", "?"), self.site_url or "?", len(existing.posts))

        budget = self._budget()
        if budget <= 0:
            log.info("Nothing to publish this run (budget 0)")
            if not self.s.dry_run:
                report.indexing = Indexer(self.s, self.http, self.state).run([], self.site_url)
            return
        items = self.collect()
        log.info("📥 %d feed items from %d feeds", len(items), report.feeds_ok)

        candidates = self.select(items, existing)
        log.info("🎯 %d candidates after filtering, ranking and de-duplication (budget %d)", len(candidates), budget)
        if not self.ai.enabled:
            self._warn("AI writer disabled or no AI key configured — using extractive news briefs")

        pub = self.s.data["publishing"]
        per_source: dict[str, int] = {}
        per_cat: dict[str, int] = {}
        live_urls: list[str] = []
        done = 0
        times = schedule_times(budget, int(pub.get("stagger_minutes", 0)))

        for item in candidates:
            if done >= budget:
                break
            if per_source.get(item.host, 0) >= int(pub["max_per_source_per_run"]):
                continue
            with group(f"📰 {item.title[:90]}"):
                log.info("   score %.1f · %s · %s", item.score, item.source, "; ".join(item.score_notes[:4]))
                try:
                    prep = self.prepare(item, existing)
                except ExtractionError as exc:
                    systemic = isinstance(exc, WriterUnavailable)
                    log.info("   ⏭️ skipped: %s", exc)
                    if not systemic:  # don't blacklist good stories because the AI was down
                        self.state.record_failure(item.url, item.title, str(exc), permanent=exc.permanent)
                    report.add(ItemOutcome(item.title, item.url, item.source, "skipped", str(exc), item.score,
                                           systemic=systemic))
                    continue
                if per_cat.get(prep.category, 0) >= int(pub["max_per_category_per_run"]):
                    log.info("   ⏭️ category '%s' already has enough posts this run", prep.category)
                    continue
                try:
                    post_url, status = self.publish(prep, existing, publish_at=times[done])
                except AuthError:
                    raise  # broken credentials fail every post → stop the run
                except PublishError as exc:
                    log.error("   ❌ Blogger rejected the post: %s", exc)
                    self.state.record_failure(item.url, item.title, str(exc))
                    report.add(ItemOutcome(item.title, item.url, item.source, "failed", str(exc), item.score,
                                           prep.quality, prep.draft.provider))
                    continue
                done += 1
                self._record_success(prep, item, post_url, status, existing, per_source, per_cat)
                if status.upper() == "LIVE" and post_url:
                    live_urls.append(post_url)
                    if not self.s.dry_run:
                        self.social.share(prep.headline, post_url, prep.meta, prep.labels,
                                          prep.images[0][0].url if prep.images else "")
                self.state.save()  # persist after every post (crash safety)
                if not self.s.dry_run:
                    time.sleep(float(pub.get("sleep_between_posts", 3)))

        if not self.s.dry_run:
            with group("🔎 Indexing & pings"):
                report.indexing = Indexer(self.s, self.http, self.state).run(live_urls, self.site_url)
            report.social = self.social.results
        for name, err in self.ai.auth_errors.items():
            self._warn(f"🔑 {name}: {err}")

    def _record_success(self, prep: Prepared, item: FeedItem, post_url: str, status: str,
                        existing: ExistingIndex, per_source: dict, per_cat: dict) -> None:
        self.state.mark_published(item.url, {
            "title": prep.headline, "post_url": post_url, "source": item.source, "category": prep.category,
            "provider": f"{prep.draft.provider}:{prep.draft.model}", "quality": prep.quality,
            "words": prep.words, "status": status,
        }, fingerprint=title_fingerprint(item.title))
        self.state.remember_title(title_fingerprint(prep.headline))
        self.state.quota_add("posts", 1, self.s.get("site.timezone", "UTC"))
        existing.titles.add(prep.headline.lower())
        existing.fingerprints.add(title_fingerprint(prep.headline))
        existing.posts.insert(0, {"title": prep.headline, "url": post_url})
        existing.canonical.add(canonical_url(item.url))
        per_source[item.host] = per_source.get(item.host, 0) + 1
        per_cat[prep.category] = per_cat.get(prep.category, 0) + 1
        label = "dry-run" if self.s.dry_run else "published"
        self.report.add(ItemOutcome(prep.headline, item.url, item.source, label, "", item.score, prep.quality,
                                    prep.draft.provider, post_url, prep.words, prep.category))
        log.info("   ✅ %s [%s · quality %d · %d words · %s] %s", status, prep.draft.provider, prep.quality,
                 prep.words, prep.category, post_url or "(draft)")

    # ───────────────────────── exit code & outputs ─────────────────────────
    def _decide_exit(self, report: RunReport) -> None:
        if report.exit_code != EXIT_OK:
            return
        published = report.count("published") + report.count("dry-run")
        attempted = published + report.count("failed") + report.count("skipped")
        min_attempts = int(self.s.get("health.min_attempts_for_failure", 4))
        systemic = any(o.systemic for o in report.outcomes)
        if published == 0 and self.s.get("health.fail_on_zero_published", True) and (
                report.count("failed") > 0 or attempted >= min_attempts or systemic):
            report.fatal_errors.append(
                f"No posts published although {attempted} candidate(s) were tried — see the log above")
            report.exit_code = EXIT_FAILED
            return
        policy = str(self.s.get("health.fail_on_ai_auth_error", "daily")).lower()
        if self.ai and self.ai.auth_errors and policy in ("always", "daily", "true"):
            last = parse_iso(self.state.data["runs"].get("last_ai_auth_alert"))
            if policy != "daily" or not last or utcnow() - last > timedelta(hours=24):
                self.state.data["runs"]["last_ai_auth_alert"] = iso()
                report.fatal_errors.append(
                    "AI key rejected: " + "; ".join(self.ai.auth_errors) +
                    " — posts were still published with the fallback writer. Fix the key to restore AI articles.")
                report.exit_code = EXIT_FAILED

    def _finish(self, report: RunReport) -> None:
        self._decide_exit(report)
        success = report.exit_code == EXIT_OK
        published = report.count("published") + report.count("dry-run")
        failures = self.state.record_run(success)
        report_dir = self.s.path(self.s.get("report.dir", "reports"))
        try:
            self.state.save()
            report.save(report_dir, int(self.s.get("report.keep_runs", 60)))
            build_dashboard(report_dir, self.state, self.s.path(self.s.get("report.dashboard", "public/index.html")),
                            self.s.site_name, self.site_url)
        except OSError as exc:
            log.warning("Could not write state/report: %s", exc)
        report.write_github_summary()
        report.write_outputs()
        self._notify(report, published, failures)
        summary = (f"🏁 Done in {report.duration_s:.0f}s — published {published}, skipped "
                   f"{report.count('skipped')}, failed {report.count('failed')}, exit code {report.exit_code}")
        (log.info if success else log.error)(summary)

    def _notify(self, report: RunReport, published: int, failures: int) -> None:
        if self.s.dry_run:
            return
        threshold = int(self.s.get("health.alert_after_consecutive_failures", 3))
        every = max(1, int(self.s.get("health.realert_every_failed_runs", 12)))
        should = False
        if report.fatal_errors:
            # alert on the N-th consecutive failure, then only every `every` failures (no spam)
            should = failures == threshold or (failures > threshold and (failures - threshold) % every == 0) \
                or report.exit_code == EXIT_CONFIG or published > 0
        elif published and self.s.get("notify.on_publish", True):
            should = True
        if should:
            try:
                self.notifier.run_summary(report)
            except Exception as exc:  # best effort
                log.debug("notify failed: %s", exc)
