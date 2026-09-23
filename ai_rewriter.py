"""Backward-compatible wrapper around :mod:`bsdc_news.ai` (v5 API).

The v5 version built a ``genai.Client`` at import time and hard-coded the
``gemini-2.5-flash`` model; every call failed with 401 in production.
"""

from bsdc_news.ai.base import GenerationRequest
from bsdc_news.ai.router import build_router
from bsdc_news.content.sanitize import sanitize_html
from bsdc_news.settings import load_settings

_router = None


def rewrite_with_gemini(title, raw_text):
    """Return article body HTML, or None when every AI provider fails."""
    global _router
    if _router is None:
        _router = build_router(load_settings())
    draft = _router.generate(GenerationRequest(title=title, text=raw_text, source="source", url=""))
    return sanitize_html(draft.body_html) if draft else None
