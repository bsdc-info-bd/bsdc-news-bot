"""Regression tests for the exact production bugs found in the Actions logs."""

import ast
import re
from pathlib import Path

from bsdc_news.content.seo import news_article_schema
from bsdc_news.indexing import INDEXING_SCOPE, INDEXNOW_ENDPOINT

ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_LINK_IN_STRING = re.compile(r"\[https?://[^\]]+\]\(https?://[^)]+\)")


def test_indexing_scope_is_a_plain_url():
    # v5: "[https://www.googleapis.com/auth/indexing](https://...)" -> "No access token in response"
    assert INDEXING_SCOPE == "https://www.googleapis.com/auth/indexing"


def test_indexnow_endpoint_is_a_plain_url():
    # v5: "No connection adapters were found for '[https://api.indexnow.org/indexnow](...)'"
    assert INDEXNOW_ENDPOINT == "https://api.indexnow.org/indexnow"


def test_schema_context_is_a_plain_url():
    schema = news_article_schema(headline="h", description="d", images=[], published="2026-09-23T00:00:00Z",
                                 site_name="bsdc news")
    assert schema["@context"] == "https://schema.org"


def test_no_markdown_links_inside_python_string_literals():
    """Guard against copy/paste from chat tools corrupting URLs again."""
    offenders = []
    for path in list(ROOT.glob("*.py")) + list((ROOT / "bsdc_news").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and MARKDOWN_LINK_IN_STRING.search(node.value):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"markdown-style links found in string literals: {offenders}"


def test_no_deprecated_utcnow():
    for path in (ROOT / "bsdc_news").rglob("*.py"):
        assert "datetime.utcnow(" not in path.read_text(encoding="utf-8"), path


def test_legacy_modules_import_without_secrets(monkeypatch):
    """v5 config.py called sys.exit(1) at import when secrets were missing."""
    import importlib
    import sys

    for var in ("BLOG_ID", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for name in ("config", "scraper", "ai_rewriter", "image_handler", "blogger_publisher", "indexing_engine"):
        sys.modules.pop(name, None)
        importlib.import_module(name)


def test_requirements_do_not_pin_old_google_auth():
    """google-auth==2.27.0 forced pip to resolve google-genai 1.x (production root cause)."""
    lines = [ln.split("#", 1)[0].strip() for ln in (ROOT / "requirements.txt").read_text().splitlines()]
    reqs = [ln for ln in lines if ln]
    assert "google-auth==2.27.0" not in reqs
    assert not any(r.startswith("google-genai") for r in reqs)  # REST client used instead


def test_default_gemini_models_are_current():
    from bsdc_news.settings import DEFAULTS

    models = DEFAULTS["ai"]["gemini_models"]
    assert models[0] != "gemini-2.5-flash"  # answered 401 ACCESS_TOKEN_TYPE_UNSUPPORTED in production
    assert len(models) >= 3  # automatic fallback chain
