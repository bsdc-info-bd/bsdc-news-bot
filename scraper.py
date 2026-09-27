"""Backward-compatible wrapper around :mod:`bsdc_news.extractor` (v5 API)."""

from bsdc_news.errors import ExtractionError
from bsdc_news.extractor import Extractor
from bsdc_news.http import HttpClient
from bsdc_news.settings import load_settings

_extractor = None


def scrape_article_data(entry_url):
    """Return ``(text, image_urls)`` or ``(None, [])`` exactly like v5 did."""
    global _extractor
    if _extractor is None:
        _extractor = Extractor(HttpClient(), load_settings())
    try:
        art = _extractor.extract(entry_url)
    except ExtractionError:
        return None, []
    return (art.text or None), [c.url for c in art.images]
