"""Automatic index submission: Google, Bing, IndexNow partners, WebSub and pings.

Public facade — the pipeline only imports from here, so the individual
submitter modules can be reorganised without touching any caller.
"""

from .core import (
    BING_SUBMIT,
    INDEXING_ENDPOINT,
    INDEXING_SCOPE,
    INDEXNOW_ENDPOINT,
    GoogleIndexer,
    Indexer,
)

__all__ = [
    "INDEXING_ENDPOINT",
    "BING_SUBMIT",
    "GOOGLE_INDEXING_ENDPOINT",
    "INDEXING_SCOPE",
    "INDEXNOW_ENDPOINT",
    "GoogleIndexer",
    "Indexer",
]
