"""Backward-compatible configuration module (v5 API).

v5 called ``sys.exit(1)`` at import time when a secret was missing, which made
every tool that imported it crash.  Validation now happens in
``bsdc_news.settings.Settings.validate`` with clear messages.
"""

from bsdc_news.settings import LEGACY_FEEDS, load_settings
from bsdc_news.settings import sanitize_secret as _sanitize

_settings = load_settings()


def sanitize_secret(key: str) -> str:
    import os

    return _sanitize(os.environ.get(key, ""))


BLOG_ID = _settings.secret("blog_id")
CLIENT_ID = _settings.secret("google_client_id")
CLIENT_SECRET = _settings.secret("google_client_secret")
REFRESH_TOKEN = _settings.secret("google_refresh_token")
INDEXING_JSON = _settings.secret("indexing_service_account_json")
GEMINI_KEY = _settings.secret("gemini_api_key")
RSS_FEEDS = [f.url for f in _settings.feeds if f.enabled] or list(LEGACY_FEEDS)
