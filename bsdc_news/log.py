"""Logging helpers: coloured console output, GitHub Actions annotations,
collapsible log groups and secret masking."""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from collections.abc import Iterator

try:  # colorama is optional at runtime
    from colorama import Fore, Style, just_fix_windows_console

    just_fix_windows_console()
except Exception:  # pragma: no cover

    class _Blank:
        def __getattr__(self, _name: str) -> str:
            return ""

    Fore = Style = _Blank()  # type: ignore[assignment]

LOGGER_NAME = "bsdc"
_SECRETS: set[str] = set()


def in_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def register_secret(value: str | None) -> None:
    """Remember a secret so it is never printed in logs."""
    if value and len(value) >= 6:
        _SECRETS.add(value)


def mask(text: str) -> str:
    for secret in sorted(_SECRETS, key=len, reverse=True):
        if secret in text:
            text = text.replace(secret, "***")
    return text


def _escape_annotation(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


class _Formatter(logging.Formatter):
    LEVEL_STYLE = {
        logging.DEBUG: Style.DIM,
        logging.INFO: "",
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def __init__(self, color: bool, annotations: bool) -> None:
        super().__init__("%(message)s")
        self.color = color
        self.annotations = annotations

    def format(self, record: logging.LogRecord) -> str:
        message = mask(super().format(record))
        if self.annotations and record.levelno >= logging.WARNING:
            kind = "error" if record.levelno >= logging.ERROR else "warning"
            return f"::{kind}::{_escape_annotation(message)}"
        style = self.LEVEL_STYLE.get(record.levelno, "") if self.color else ""
        return f"{style}{message}{Style.RESET_ALL}" if style else message


def setup_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    color = in_github_actions() or sys.stdout.isatty()
    handler.setFormatter(_Formatter(color=color, annotations=in_github_actions()))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False
    # Third-party libraries are chatty (e.g. trafilatura logs "discarding data" for short pages
    # that we handle with our own fallbacks) — keep the run log readable.
    for noisy in ("trafilatura", "htmldate", "courlan", "justext", "charset_normalizer", "urllib3",
                  "googleapiclient.discovery_cache", "googleapiclient.http", "cloudscraper"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


@contextlib.contextmanager
def group(title: str) -> Iterator[None]:
    """Collapsible section in GitHub Actions, a header line elsewhere."""
    if in_github_actions():
        print(f"::group::{title}", flush=True)
        try:
            yield
        finally:
            print("::endgroup::", flush=True)
    else:
        get_logger().info("── %s ──", title)
        yield
