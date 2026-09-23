"""Free OpenAI-compatible providers: Groq, OpenRouter (free router),
Cloudflare Workers AI and Hugging Face Inference Providers."""

from __future__ import annotations

import time

import requests

from ..errors import AuthError, ContentRejected, ModelUnavailableError, ProviderError, QuotaError
from ..log import get_logger
from .base import AIProvider, GenerationRequest

log = get_logger("ai.openai")


class OpenAICompatProvider(AIProvider):
    name = "openai-compatible"
    base_url = ""
    json_mode = True
    signup = ""
    max_tokens_cap = 8000          # upper bound for "max_tokens" sent to the provider
    source_chars_cap = 0           # 0 = use the request's max_source_chars
    reasoning_effort = ""          # e.g. "low" for gpt-oss reasoning models (Groq)

    def __init__(self, api_key: str, models: list[str], timeout: float = 120.0, session=None,
                 base_url: str | None = None, extra_headers: dict | None = None) -> None:
        super().__init__(models, timeout)
        self.api_key = api_key
        self.session = session or requests.Session()
        if base_url:
            self.base_url = base_url
        self.extra_headers = extra_headers or {}
        self._json_ok: dict[str, bool] = {}

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.models and self.base_url)

    def _payload(self, model: str, req: GenerationRequest, json_mode: bool) -> dict:
        if self.source_chars_cap and req.max_source_chars > self.source_chars_cap:
            from dataclasses import replace

            req = replace(req, max_source_chars=self.source_chars_cap)
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": req.system_prompt()},
                {"role": "user", "content": req.user_prompt()},
            ],
            "temperature": req.temperature,
            "max_tokens": min(req.max_output_tokens, self.max_tokens_cap),
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort and "gpt-oss" in model:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def _complete(self, model: str, req: GenerationRequest) -> str:
        json_mode = self.json_mode and self._json_ok.get(model, True)
        for attempt in range(3):
            try:
                resp = self.session.post(
                    self.base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                             **self.extra_headers},
                    json=self._payload(model, req, json_mode),
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise ProviderError(f"{self.name} network error: {exc}", retryable=True) from exc

            status = resp.status_code
            if status == 200:
                try:
                    data = resp.json()
                    text = data["choices"][0]["message"].get("content") or ""
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise ContentRejected(f"{self.name}: malformed response ({exc})") from exc
                if not text.strip():
                    raise ContentRejected(f"{self.name}: empty completion")
                return text

            body = resp.text[:400]
            if status == 400 and json_mode and ("response_format" in body or "json" in body.lower()):
                self._json_ok[model] = False
                json_mode = False
                continue
            if status in (401, 403):
                raise AuthError(f"{self.name} rejected the API key (HTTP {status}): {body[:160]}",
                                hint=f"Create a free key at {self.signup} and update the secret")
            if status == 404 or (status == 400 and "model" in body.lower() and
                                 ("not found" in body.lower() or "does not exist" in body.lower()
                                  or "decommissioned" in body.lower())):
                exc = ModelUnavailableError(f"{self.name}: model {model} unavailable: {body[:160]}")
                exc.model_unavailable = True  # type: ignore[attr-defined]
                raise exc
            if status == 429:
                retry = resp.headers.get("retry-after")
                wait = float(retry) if retry and retry.replace(".", "", 1).isdigit() else None
                if wait and wait <= 15 and attempt < 2:
                    time.sleep(wait + 1)
                    continue
                raise QuotaError(f"{self.name} {model} rate limited: {body[:160]}", retry_after=wait)
            if status == 402:
                raise QuotaError(f"{self.name}: free credits exhausted ({body[:120]})")
            if status == 413:
                raise ProviderError(f"{self.name} {model}: request too large for the free tier ({body[:120]})")
            if status >= 500 and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            raise ProviderError(f"{self.name} {model} HTTP {status}: {body[:160]}", retryable=status >= 500)
        raise ProviderError(f"{self.name}: retries exhausted", retryable=True)


class GroqProvider(OpenAICompatProvider):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1"
    signup = "https://console.groq.com/keys"
    # Free tier: 8,000 tokens/minute per model and a request may not exceed it
    # (input + max_tokens) → keep requests around 7k tokens.
    max_tokens_cap = 3800
    source_chars_cap = 9000
    reasoning_effort = "low"


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"
    base_url = "https://openrouter.ai/api/v1"
    signup = "https://openrouter.ai/settings/keys"

    def __init__(self, api_key: str, models: list[str], timeout: float = 120.0, session=None,
                 site_url: str = "", site_name: str = "") -> None:
        headers = {"X-Title": site_name or "bsdc news"}
        if site_url:
            headers["HTTP-Referer"] = site_url
        super().__init__(api_key, models, timeout, session, extra_headers=headers)


class CloudflareProvider(OpenAICompatProvider):
    name = "cloudflare"
    json_mode = False
    signup = "https://dash.cloudflare.com/profile/api-tokens"
    max_tokens_cap = 4096

    def __init__(self, account_id: str, api_token: str, models: list[str], timeout: float = 120.0,
                 session=None) -> None:
        base = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1" if account_id else ""
        super().__init__(api_token, models, timeout, session, base_url=base)


class HuggingFaceProvider(OpenAICompatProvider):
    name = "huggingface"
    base_url = "https://router.huggingface.co/v1"
    json_mode = False
    signup = "https://huggingface.co/settings/tokens"
    max_tokens_cap = 4096
