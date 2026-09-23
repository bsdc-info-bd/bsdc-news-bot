"""Exception hierarchy used across the pipeline.

Errors are *classified* so the orchestrator can decide what to do:
retry, fall back to another provider, skip one article, or stop the run.
"""

from __future__ import annotations


class BotError(Exception):
    """Base class for all bsdc news errors."""

    hint: str = ""

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        if hint:
            self.hint = hint

    def describe(self) -> str:
        text = str(self)
        return f"{text}\n   ↳ Fix: {self.hint}" if self.hint else text


class ConfigError(BotError):
    """Invalid or missing configuration / secrets."""


class AuthError(BotError):
    """Credentials were rejected by a remote service."""


class QuotaError(BotError):
    """A rate limit or daily quota was hit."""

    def __init__(self, message: str, *, retry_after: float | None = None, hint: str = "") -> None:
        super().__init__(message, hint=hint)
        self.retry_after = retry_after


class ProviderError(BotError):
    """An AI provider failed for a reason that is not auth or quota."""

    def __init__(self, message: str, *, retryable: bool = False, hint: str = "") -> None:
        super().__init__(message, hint=hint)
        self.retryable = retryable


class ModelUnavailableError(ProviderError):
    """The requested model does not exist or is not available to this key."""


class ContentRejected(BotError):
    """Generated or extracted content failed a quality gate."""


class ExtractionError(BotError):
    """The article page could not be fetched or parsed."""

    def __init__(self, message: str, *, permanent: bool = False, hint: str = "") -> None:
        super().__init__(message, hint=hint)
        self.permanent = permanent


class WriterUnavailable(ExtractionError):
    """No writer could produce the article (AI down and fallback disabled) — a system problem,
    not a property of the article, so it counts towards a failed run."""


class PublishError(BotError):
    """Blogger refused the post."""

    def __init__(self, message: str, *, retryable: bool = False, hint: str = "") -> None:
        super().__init__(message, hint=hint)
        self.retryable = retryable
