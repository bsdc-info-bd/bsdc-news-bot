"""bsdc news — a smart, fully automated news publishing system for Blogger.

The package is organised as a pipeline:

    feeds -> ranking -> dedupe -> extractor -> images -> ai (or brief)
          -> content (sanitize, quality, render, schema) -> blogger
          -> indexing / notify / social -> report + state

Everything runs on free services (GitHub Actions, Blogger API, free AI tiers).
"""

__version__ = "6.0.0"
APP_NAME = "bsdc news Smart Publisher"
PROJECT_URL = "https://github.com/bsdc-info-bd/bsdc-news-bot"
