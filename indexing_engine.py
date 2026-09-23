"""Backward-compatible indexing helper (v5 API).

Fixes the two production errors seen in the Actions logs:
* The Google Indexing API scope string had been pasted as a Markdown link
  (``[url](url)``) → "No access token in response" for every URL.
* The IndexNow endpoint had been pasted the same way
  → "No connection adapters were found".
"""

from bsdc_news.http import HttpClient
from bsdc_news.indexing import INDEXING_SCOPE, INDEXNOW_ENDPOINT, Indexer  # noqa: F401
from bsdc_news.settings import load_settings
from bsdc_news.state import State


def push_instant_indexing(urls):
    if not urls:
        return {}
    settings = load_settings()
    state = State.load(settings.path(settings.get("state.path", "data/state.json")))
    results = Indexer(settings, HttpClient(), state).run(list(urls), "")
    state.save()
    return results
