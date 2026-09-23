"""Failover router: tries providers in order, pauses broken/exhausted ones
(persisted in state), enforces a per-run call budget and reports health."""

from __future__ import annotations

from datetime import timedelta

from ..errors import AuthError, BotError, ContentRejected, ProviderError, QuotaError
from ..log import get_logger
from ..utils import next_midnight, utcnow
from .base import AIProvider, ArticleDraft, GenerationRequest
from .gemini import GeminiProvider
from .openai_compat import CloudflareProvider, GroqProvider, HuggingFaceProvider, OpenRouterProvider

log = get_logger("ai")


class AIRouter:
    def __init__(self, providers: list[AIProvider], state=None, max_calls: int = 12) -> None:
        self.providers = [p for p in providers if p.available]
        self.state = state
        self.max_calls = max_calls
        self.calls = 0
        self.auth_errors: dict[str, str] = {}
        self.errors: list[str] = []
        self.usage: dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    def active_providers(self) -> list[AIProvider]:
        out = []
        for p in self.providers:
            if p.name in self.auth_errors:
                continue
            if self.state is not None and self.state.provider_disabled(p.name, p.fingerprint):
                continue
            out.append(p)
        return out

    def generate(self, req: GenerationRequest) -> ArticleDraft | None:
        if self.calls >= self.max_calls:
            log.info("   🤖 AI call budget for this run reached (%d)", self.max_calls)
            return None
        for provider in self.active_providers():
            self.calls += 1
            try:
                draft = provider.generate(req)
                self.usage[f"{provider.name}:{draft.model}"] = self.usage.get(f"{provider.name}:{draft.model}", 0) + 1
                if self.state is not None:
                    self.state.provider_result(provider.name, True)
                return draft
            except AuthError as exc:
                self.auth_errors[provider.name] = exc.describe()
                self.errors.append(f"{provider.name}: {exc}")
                log.error("🔑 %s authentication failed — provider disabled for this run.\n   %s",
                          provider.name, exc.describe())
                if self.state is not None:
                    self.state.provider_result(provider.name, False, str(exc))
                    self.state.disable_provider(provider.name, utcnow() + timedelta(hours=6), str(exc),
                                                provider.fingerprint)
            except QuotaError as exc:
                self.errors.append(f"{provider.name}: {exc}")
                log.warning("⏳ %s quota/rate limit: %s", provider.name, exc)
                if self.state is not None:
                    self.state.provider_result(provider.name, False, str(exc))
                    until = utcnow() + timedelta(seconds=exc.retry_after) if exc.retry_after else None
                    if until is None or until < utcnow() + timedelta(minutes=5):
                        until = next_midnight("America/Los_Angeles") if provider.name == "gemini" \
                            else utcnow() + timedelta(hours=1)
                    self.state.disable_provider(provider.name, until, str(exc), provider.fingerprint)
            except (ProviderError, ContentRejected) as exc:
                self.errors.append(f"{provider.name}: {exc}")
                log.warning("⚠️ %s failed: %s", provider.name, exc)
                if self.state is not None:
                    self.state.provider_result(provider.name, False, str(exc))
            except BotError as exc:  # pragma: no cover - defensive
                self.errors.append(f"{provider.name}: {exc}")
                log.warning("⚠️ %s error: %s", provider.name, exc)
            except Exception as exc:  # never let one provider crash the run
                self.errors.append(f"{provider.name}: unexpected {type(exc).__name__}: {exc}")
                log.warning("⚠️ %s unexpected error: %s", provider.name, exc)
            if self.calls >= self.max_calls:
                break
        return None

    def health(self) -> dict:
        return {
            "configured": [p.name for p in self.providers],
            "auth_errors": self.auth_errors,
            "calls": self.calls,
            "usage": self.usage,
        }


def build_router(settings, state=None, session=None) -> AIRouter:
    if not settings.get("ai.enabled", True):
        return AIRouter([], state)
    timeout = float(settings.get("ai.timeout", 120))
    order = [p.strip().lower() for p in settings.get("ai.providers", [])]
    factories = {
        "gemini": lambda: GeminiProvider(settings.secret("gemini_api_key"),
                                         settings.get("ai.gemini_models", []), timeout, session),
        "groq": lambda: GroqProvider(settings.secret("groq_api_key"),
                                     settings.get("ai.groq_models", []), timeout, session),
        "openrouter": lambda: OpenRouterProvider(settings.secret("openrouter_api_key"),
                                                 settings.get("ai.openrouter_models", []), timeout, session,
                                                 site_url=settings.get("site.url", ""),
                                                 site_name=settings.site_name),
        "cloudflare": lambda: CloudflareProvider(settings.secret("cloudflare_account_id"),
                                                 settings.secret("cloudflare_api_token"),
                                                 settings.get("ai.cloudflare_models", []), timeout, session),
        "huggingface": lambda: HuggingFaceProvider(settings.secret("huggingface_token"),
                                                   settings.get("ai.huggingface_models", []), timeout, session),
    }
    providers = [factories[name]() for name in order if name in factories]
    return AIRouter(providers, state, int(settings.get("ai.max_calls_per_run", 12)))
