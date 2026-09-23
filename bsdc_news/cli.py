"""Command line interface.

    python main.py                      # normal scheduled run (same as before)
    python -m bsdc_news run --dry-run   # full pipeline, nothing is published
    python -m bsdc_news doctor          # check every secret/API and explain fixes
    python -m bsdc_news feeds           # test all feeds
    python -m bsdc_news preview URL     # render one article to preview.html
    python -m bsdc_news dashboard       # rebuild docs/index.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .errors import BotError, ConfigError
from .log import get_logger, setup_logging
from .settings import load_settings

log = get_logger()


def _banner(mode: str) -> None:
    log.info("=" * 60)
    log.info("🚀 %s v%s — %s", APP_NAME, __version__, mode)
    log.info("=" * 60)


def cmd_run(args) -> int:
    from .pipeline import Pipeline

    overrides = {}
    if args.max_posts is not None:
        overrides.setdefault("publishing", {})["max_posts_per_run"] = args.max_posts
    if args.draft:
        overrides.setdefault("publishing", {})["mode"] = "draft"
    if args.no_ai:
        overrides.setdefault("ai", {})["enabled"] = False
    settings = load_settings(dry_run=args.dry_run, offline=args.offline, overrides=overrides)
    setup_logging(args.log_level or settings.get("logging.level", "INFO"))
    _banner("DRY RUN (nothing will be published)" if args.dry_run else settings.get("publishing.mode", "live"))
    report = Pipeline(settings).run()
    if args.json:
        print(json.dumps({"exit_code": report.exit_code, "published": report.published,
                          "errors": report.fatal_errors}, indent=1))
    return report.exit_code


def cmd_doctor(args) -> int:
    from .doctor import run_doctor

    settings = load_settings()
    setup_logging(args.log_level or "INFO")
    _banner("doctor")
    return run_doctor(settings, deep=not args.quick)


def cmd_feeds(args) -> int:
    from .feeds import FeedFetcher
    from .http import HttpClient

    settings = load_settings()
    setup_logging(args.log_level or "INFO")
    _banner("feed check")
    results = FeedFetcher(HttpClient()).fetch_all(settings.feeds)
    bad = [r for r in results if r.error]
    log.info("%d/%d feeds OK", len(results) - len(bad), len(results))
    for r in bad:
        log.error("✗ %s — %s", r.feed.url, r.error)
    return 1 if len(bad) == len(results) else 0


def cmd_preview(args) -> int:
    from .blogger import ExistingIndex
    from .content.render import RenderInput, build_post_html
    from .feeds import FeedItem
    from .pipeline import Pipeline
    from .utils import host_of, utcnow

    settings = load_settings(dry_run=True, overrides={"ai": {"enabled": not args.no_ai}})
    setup_logging(args.log_level or "INFO")
    _banner("preview")
    pipe = Pipeline(settings)
    item = FeedItem(title=args.title or "", url=args.url, source=host_of(args.url), source_url=args.url,
                    category="Technology", published=utcnow())
    art = pipe.extractor.extract(args.url)
    item.title = item.title or art.title or args.url
    item.source = art.sitename or item.source
    prep = pipe.prepare(item, ExistingIndex([]))
    html_doc = build_post_html(RenderInput(
        headline=prep.headline, body_html=prep.draft.body_html, meta_description=prep.meta,
        category=prep.category, labels=prep.labels, source_name=item.source, source_url=item.url,
        words=prep.words, images=prep.images, key_points=prep.draft.key_points, faq=prep.draft.faq,
        ai_generated=prep.draft.ai_generated), settings, post_url="https://example.blogspot.com/preview.html")
    out = Path(args.out)
    out.write_text(f"<!doctype html><meta charset=utf-8><title>{prep.headline}</title>"
                   f"<body style='max-width:780px;margin:30px auto;padding:0 16px'>"
                   f"<h1 style='font-family:Georgia,serif'>{prep.headline}</h1>{html_doc}</body>", encoding="utf-8")
    log.info("✅ Preview written to %s (writer: %s, quality %d, %d words, labels %s)",
             out, prep.draft.provider, prep.quality, prep.words, ", ".join(prep.labels))
    return 0


def cmd_dashboard(args) -> int:
    from .report import build_dashboard
    from .state import State

    settings = load_settings()
    setup_logging(args.log_level or "INFO")
    state = State.load(settings.path(settings.get("state.path", "data/state.json")))
    out = settings.path(settings.get("report.dashboard", "docs/index.html"))
    build_dashboard(settings.path(settings.get("report.dir", "reports")), state, out, settings.site_name,
                    state.data.get("blog", {}).get("url", ""))
    log.info("Dashboard written to %s", out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bsdc_news", description=f"{APP_NAME} v{__version__}")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run the publishing pipeline (default)")
    run.add_argument("--dry-run", action="store_true", help="do everything except publishing")
    run.add_argument("--offline", action="store_true", help="skip optional network calls (trends, image checks)")
    run.add_argument("--max-posts", type=int, default=None)
    run.add_argument("--draft", action="store_true", help="save posts as Blogger drafts")
    run.add_argument("--no-ai", action="store_true", help="use the extractive brief writer only")
    run.add_argument("--json", action="store_true", help="print a JSON summary at the end")
    run.set_defaults(func=cmd_run)

    doc = sub.add_parser("doctor", help="diagnose secrets, APIs and feeds")
    doc.add_argument("--quick", action="store_true", help="skip live API calls")
    doc.set_defaults(func=cmd_doctor)

    feeds = sub.add_parser("feeds", help="check every configured feed")
    feeds.set_defaults(func=cmd_feeds)

    prev = sub.add_parser("preview", help="render a single article URL to an HTML file (never publishes)")
    prev.add_argument("url")
    prev.add_argument("--title", default="")
    prev.add_argument("--out", default="preview.html")
    prev.add_argument("--no-ai", action="store_true")
    prev.set_defaults(func=cmd_preview)

    dash = sub.add_parser("dashboard", help="rebuild the static status dashboard")
    dash.set_defaults(func=cmd_dashboard)
    return parser


def load_dotenv(path: Path | None = None) -> int:
    """Minimal .env loader for local runs (KEY=VALUE lines; real environment variables win)."""
    import os

    path = path or Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return 0
    count = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    load_dotenv()
    parser = build_parser()
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--log-level"):
        argv = ["run", *argv]  # `python main.py --dry-run` works too
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):  # only global flags given, e.g. `--log-level DEBUG`
        args = parser.parse_args([*argv, "run"])
    setup_logging(args.log_level or "INFO")
    try:
        return int(args.func(args) or 0)
    except ConfigError as exc:
        log.error("❌ Configuration error:\n%s", exc.describe())
        return 2
    except BotError as exc:
        log.error("❌ %s", exc.describe())
        return 1
    except KeyboardInterrupt:
        return 130
