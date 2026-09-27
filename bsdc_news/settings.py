"""Configuration: ``config/settings.yaml`` + ``config/feeds.yaml`` + environment.

Precedence (highest first): CLI flags → environment variables (``BSDC_*``) →
YAML files → built-in defaults.  Secrets are **only** read from the
environment and keep the exact names used by the original bot
(``BLOG_ID``, ``GOOGLE_CLIENT_ID`` … ``GEMINI_API_KEY``).
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .log import get_logger, register_secret

log = get_logger("settings")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("BSDC_CONFIG_DIR", ROOT / "config"))

DEFAULTS: dict[str, Any] = {
    "site": {
        "name": "bsdc news",
        "url": "",  # e.g. https://bsdcnews.blogspot.com — auto-detected from Blogger when empty
        "tagline": "Structured coverage of technology, software and the digital world.",
        "language": "en",
        "timezone": "Asia/Dhaka",
        "logo_url": "",
        "author_name": "bsdc news Desk",
        "about": "bsdc news is a digital news engine providing structured coverage on software "
                 "architecture, web technologies, and tech updates.",
        "social": {"facebook": "", "x": "", "telegram": "", "youtube": ""},
    },
    "publishing": {
        "max_posts_per_run": 4,
        "max_posts_per_day": 24,
        "spread_evenly": True,  # pace posts across the day instead of using the daily limit early
        "max_per_source_per_run": 2,
        "max_per_category_per_run": 2,
        "max_article_age_hours": 36,
        "mode": "live",  # live | draft
        "stagger_minutes": 0,  # >0 schedules posts N minutes apart via Blogger
        "quiet_hours": "",  # e.g. "01:00-06:00" in site timezone
        "quiet_hours_max_posts": 1,
        "ai_failure_mode": "brief",  # brief | draft | skip
        "min_quality_score": 55,
        "require_image": True,
        "labels_max": 6,
        "default_labels": ["Tech News"],
        "jump_break": True,  # <!--more--> after summary + hero image (homepage cards)
        "brief_label": "News Brief",  # extra label on posts written without AI ("" = none)
        "sleep_between_posts": 3,
    },
    # The writer is the local cortex engine. It needs no API key, no provider list and
    # no network access, so its settings are all about editorial behaviour.
    "writer": {
        "enabled": True,
        "target_words": 700,
        "min_words": 420,
        "max_source_chars": 12000,
        "grade_target": 12.0,          # simplify prose above this US school grade
        "rewrite": True,               # paraphrase sentences copied verbatim
        "min_facts": 3,                # fewer facts than this cannot support an article
        "min_confidence": 0.30,        # reject a draft the source does not support
        "quality_passes": 2,           # revision rounds against the quality gate
        "novelty_threshold": 0.42,     # below this the story is already covered
        "languages": ["en"],
        "tone": "news",                # news | analysis | explainer | brief
    },
    # Legacy aliases: older configuration files still say [ai]. They keep working.
    "ai": {
        "enabled": True,
        "min_words": 420,
        "target_words": 700,
        "max_source_chars": 12000,
    },
    "extraction": {
        "min_words": 180,
        "timeout": 20,
        "respect_robots": True,
        "max_images": 4,
        "min_image_width": 480,
    },
    "images": {
        "proxy": True,  # serve images through the free wsrv.nl CDN (resized, webp)
        "proxy_width": 1200,
        "openverse_fallback": True,
        "check_dimensions": True,
    },
    "ranking": {
        "trends_geo": ["US", "BD"],
        "trend_boost": 12,
        "priority_keywords": ["ai", "openai", "google", "apple", "microsoft", "nvidia", "samsung",
                              "android", "iphone", "security", "bangladesh", "chip", "gemini",
                              "chatgpt", "tesla", "spacex", "meta", "linux", "windows"],
        "keyword_boost": 3,
        "freshness_half_life_hours": 10,
        "cluster_similarity": 0.55,
        "candidates_to_try": 20,
    },
    "filters": {
        "blocked_keywords": ["promo code", "coupon", "coupons", "discount code", "deal alert",
                             "deals:", "% off", "sponsored", "giveaway", "best deals",
                             "prime day", "black friday", "cyber monday", "horoscope",
                             "lottery", "casino", "betting", "onlyfans", "nsfw", "porn"],
        "blocked_url_patterns": ["/deals/", "/coupons/", "/coupon", "/promo", "/shopping/",
                                 "/sponsored/", "/video/", "/videos/", "/podcast", "/gallery/",
                                 "/live/", "/liveblog"],
        "blocked_domains": [],
        "required_language": "en",
        "min_title_words": 4,
    },
    "indexing": {
        "google_indexing_api": True,
        "google_daily_quota": 200,
        "indexnow": True,
        "indexnow_key": "",  # optional: IndexNow key (host the key file on your domain)
        "indexnow_key_location": "",
        "websub_ping": True,
        "bing_api_key": "",
    },
    "notify": {
        "on_publish": True,
        "telegram": True,
        "discord": True,
        "slack": True,
    },
    "social": {
        "telegram_channel_post": True,
        "facebook_page": True,
        "mastodon": True,
        "bluesky": True,
    },
    "state": {
        "path": "data/state.json",
        "retention_days": 30,
        "failed_retry_hours": 12,
        "max_failed_attempts": 2,
    },
    "report": {
        "dir": "reports",
        "keep_runs": 60,
        "dashboard": "public/index.html",
    },
    "health": {
        "fail_on_zero_published": True,
        # A rejected AI key: posts still go out (brief writer) but the run turns red so you notice.
        # always | daily (at most one red run per 24h) | never
        "fail_on_ai_auth_error": "daily",
        "min_attempts_for_failure": 4,  # 0 published after trying >= N candidates = failed run
        "alert_after_consecutive_failures": 3,
        "realert_every_failed_runs": 12,
    },
    "http": {
        "per_host_interval": 0.8,
        "retries": 2,
    },
    "logging": {"level": "INFO"},
}

SECRET_ENV = {
    "blog_id": "BLOG_ID",
    "google_client_id": "GOOGLE_CLIENT_ID",
    "google_client_secret": "GOOGLE_CLIENT_SECRET",
    "google_refresh_token": "GOOGLE_REFRESH_TOKEN",
    "indexing_service_account_json": "INDEXING_SERVICE_ACCOUNT_JSON",
    "gemini_api_key": "GEMINI_API_KEY",
    "groq_api_key": "GROQ_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "cloudflare_account_id": "CLOUDFLARE_ACCOUNT_ID",
    "cloudflare_api_token": "CLOUDFLARE_API_TOKEN",
    "huggingface_token": "HF_TOKEN",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "telegram_channel_id": "TELEGRAM_CHANNEL_ID",
    "discord_webhook_url": "DISCORD_WEBHOOK_URL",
    "slack_webhook_url": "SLACK_WEBHOOK_URL",
    "facebook_page_id": "FACEBOOK_PAGE_ID",
    "facebook_page_token": "FACEBOOK_PAGE_TOKEN",
    "mastodon_base_url": "MASTODON_BASE_URL",
    "mastodon_token": "MASTODON_ACCESS_TOKEN",
    "bluesky_handle": "BLUESKY_HANDLE",
    "bluesky_app_password": "BLUESKY_APP_PASSWORD",
    "indexnow_key": "INDEXNOW_KEY",
    "bing_api_key": "BING_WEBMASTER_API_KEY",
    "openverse_client_id": "OPENVERSE_CLIENT_ID",
    "openverse_client_secret": "OPENVERSE_CLIENT_SECRET",
}

# Environment overrides for common knobs (handy for workflow_dispatch inputs)
ENV_OVERRIDES = {
    "BSDC_MAX_POSTS": ("publishing", "max_posts_per_run", int),
    "BSDC_MAX_POSTS_PER_DAY": ("publishing", "max_posts_per_day", int),
    "BSDC_MODE": ("publishing", "mode", str),
    "BSDC_AI_FAILURE_MODE": ("publishing", "ai_failure_mode", str),
    "BSDC_MIN_QUALITY": ("publishing", "min_quality_score", int),
    "BSDC_SITE_URL": ("site", "url", str),
    "BSDC_SITE_NAME": ("site", "name", str),
    "BSDC_TIMEZONE": ("site", "timezone", str),
    "BSDC_WRITER_ENABLED": ("writer", "enabled", "bool"),
    "BSDC_WRITER_TARGET_WORDS": ("writer", "target_words", int),
    "BSDC_WRITER_MIN_WORDS": ("writer", "min_words", int),
    "BSDC_WRITER_GRADE_TARGET": ("writer", "grade_target", float),
    "BSDC_WRITER_TONE": ("writer", "tone", str),
    "BSDC_WRITER_LANGUAGES": ("writer", "languages", "list"),
    "BSDC_AI_ENABLED": ("writer", "enabled", "bool"),   # legacy name, same switch
    "BSDC_LOG_LEVEL": ("logging", "level", str),
    "BSDC_STATE_PATH": ("state", "path", str),
    "BSDC_IMAGE_PROXY": ("images", "proxy", "bool"),
    "BSDC_REPORT_DIR": ("report", "dir", str),
    "BSDC_DASHBOARD": ("report", "dashboard", str),
}


def sanitize_secret(value: str | None) -> str:
    """Trim whitespace and stray quotes/brackets pasted by accident (kept from v5)."""
    if value is None:
        return ""
    value = str(value).strip()
    # Only strip wrapping characters, never characters inside the secret
    while len(value) >= 2 and value[0] in "\"'[" and value[-1] in "\"']":
        value = value[1:-1].strip()
    return value.strip()


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("PyYAML is required to read config files", hint="pip install -r requirements.txt") from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def _coerce(value: str, kind) -> Any:
    if kind == "bool":
        return value.strip().lower() in ("1", "true", "yes", "on")
    if kind == "list":
        return [v.strip() for v in re.split(r"[,\n]", value) if v.strip()]
    return kind(value)


@dataclass
class Feed:
    url: str
    name: str = ""
    category: str = "Technology"
    weight: float = 1.0
    language: str = "en"
    enabled: bool = True
    max_items: int = 15
    region: str = ""


@dataclass
class Settings:
    data: dict
    feeds: list[Feed]
    secrets: dict[str, str]
    root: Path = ROOT
    dry_run: bool = False
    offline: bool = False
    categories: dict = field(default_factory=dict)

    # convenient accessors
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def secret(self, name: str) -> str:
        return self.secrets.get(name, "")

    def path(self, relative: str) -> Path:
        p = Path(relative)
        return p if p.is_absolute() else self.root / p

    @property
    def site_name(self) -> str:
        return self.get("site.name", "bsdc news")

    def validate(self, require_publish: bool = True) -> list[str]:
        """Return a list of warnings; raise ConfigError for fatal problems."""
        warnings: list[str] = []
        problems: list[str] = []
        pub = self.data["publishing"]
        if pub["mode"] not in ("live", "draft"):
            problems.append("publishing.mode must be 'live' or 'draft'")
        if pub["ai_failure_mode"] not in ("brief", "draft", "skip"):
            problems.append("publishing.ai_failure_mode must be brief, draft or skip")
        if int(pub["max_posts_per_run"]) < 0:
            problems.append("publishing.max_posts_per_run must be >= 0")
        if not [f for f in self.feeds if f.enabled]:
            problems.append("config/feeds.yaml has no enabled feeds")

        if require_publish and not self.dry_run:
            missing = [env for key, env in SECRET_ENV.items()
                       if key in ("blog_id", "google_client_id", "google_client_secret",
                                  "google_refresh_token") and not self.secrets.get(key)]
            if missing:
                problems.append(
                    "Missing required GitHub Secrets: " + ", ".join(missing)
                    + " (Settings → Secrets and variables → Actions)")
            if self.secrets.get("blog_id") and not re.fullmatch(r"\d{5,25}", self.secrets["blog_id"]):
                problems.append("BLOG_ID must be the numeric Blogger blog ID (Blogger dashboard URL → blogID=…)")

        sa_json = self.secrets.get("indexing_service_account_json")
        if sa_json:
            try:
                info = json.loads(sa_json)
                if info.get("type") != "service_account" or "private_key" not in info:
                    warnings.append("INDEXING_SERVICE_ACCOUNT_JSON is not a service-account key file")
            except ValueError:
                warnings.append("INDEXING_SERVICE_ACCOUNT_JSON is not valid JSON — Google Indexing API disabled")

        # Articles are written by the local engine, so no model key is required.
        # Legacy AI secrets, if still present, are simply ignored.
        legacy_keys = [k for k in ("gemini_api_key", "groq_api_key", "openrouter_api_key",
                                   "cloudflare_api_token", "huggingface_token") if self.secrets.get(k)]
        if legacy_keys:
            warnings.append("Unused legacy AI secret(s) present and ignored: "
                            + ", ".join(legacy_keys) + " — the writer is fully local")

        if problems:
            raise ConfigError("\n".join(f"• {p}" for p in problems),
                              hint="See docs/SETUP.md for step-by-step instructions")
        return warnings


def _load_feeds(path: Path) -> tuple[list[Feed], dict]:
    raw = _load_yaml(path)
    feeds: list[Feed] = []
    for item in raw.get("feeds", []) or []:
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict) or not item.get("url"):
            continue
        feeds.append(Feed(
            url=str(item["url"]).strip(),
            name=str(item.get("name", "")),
            category=str(item.get("category", "Technology")),
            weight=float(item.get("weight", 1.0)),
            language=str(item.get("language", "en")),
            enabled=bool(item.get("enabled", True)),
            max_items=int(item.get("max_items", 15)),
            region=str(item.get("region", "")),
        ))
    return feeds, raw.get("categories", {}) or {}


LEGACY_FEEDS = [
    "https://techcrunch.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml",
    "https://www.wired.com/feed/rss",
    "https://www.engadget.com/rss.xml",
    "https://www.zdnet.com/news/rss.xml",
]


def load_settings(config_dir: Path | None = None, *, dry_run: bool = False, offline: bool = False,
                  overrides: dict | None = None, env: dict | None = None) -> Settings:
    env = os.environ if env is None else env
    config_dir = Path(config_dir or CONFIG_DIR)
    data = deep_merge(DEFAULTS, _load_yaml(config_dir / "settings.yaml"))

    for var, (section, key, kind) in ENV_OVERRIDES.items():
        if env.get(var, "").strip():
            try:
                data[section][key] = _coerce(env[var], kind)
            except (TypeError, ValueError):
                log.warning("Ignoring invalid value for %s", var)
    if overrides:
        data = deep_merge(data, overrides)

    feeds, categories = _load_feeds(config_dir / "feeds.yaml")
    if not feeds:
        feeds = [Feed(url=u) for u in LEGACY_FEEDS]

    secrets = {key: sanitize_secret(env.get(var)) for key, var in SECRET_ENV.items()}
    # INDEXNOW / Bing keys can also come from settings.yaml
    secrets["indexnow_key"] = secrets["indexnow_key"] or str(data["indexing"].get("indexnow_key") or "")
    secrets["bing_api_key"] = secrets["bing_api_key"] or str(data["indexing"].get("bing_api_key") or "")
    for key, value in secrets.items():
        if key not in ("blog_id", "telegram_chat_id", "telegram_channel_id", "facebook_page_id",
                       "mastodon_base_url", "bluesky_handle", "cloudflare_account_id"):
            register_secret(value)

    return Settings(data=data, feeds=feeds, secrets=secrets, root=ROOT, dry_run=dry_run,
                    offline=offline, categories=categories)
