"""Google Gemini (free tier) via the REST ``generateContent`` endpoint.

Why REST instead of the SDK?  The old ``requirements.txt`` pinned
``google-auth==2.27.0`` which silently forced pip to install an ancient
``google-genai`` 1.x.  Talking to the REST API with ``requests`` removes that
whole class of dependency problems and gives us precise error handling.

Error classification (from real production logs):
* 401 ``ACCESS_TOKEN_TYPE_UNSUPPORTED`` – returned both for retired models and
  for keys Google no longer accepts.  We try the next model first; if every
  model answers 401 the key itself is the problem.
* 404 – model not available for this key → next model.
* 429 – rate limit / daily quota → next model, provider paused if exhausted.
"""

from __future__ import annotations

import re
import time

import requests

from ..errors import AuthError, ContentRejected, ModelUnavailableError, ProviderError, QuotaError
from ..log import get_logger
from .base import AIProvider, ArticleDraft, GenerationRequest, parse_draft

log = get_logger("ai.gemini")

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
KEY_HELP = ("Create a NEW key at https://aistudio.google.com/api-keys (new keys start with 'AQ.'), "
            "then update the GEMINI_API_KEY repository secret. Standard 'AIza…' keys are being "
            "rejected by the Gemini API since September 2026.")


def describe_key(key: str) -> str:
    """Human description of a key's type without revealing it."""
    if not key:
        return "missing"
    if key.startswith("AQ."):
        return f"auth key (AQ.…, {len(key)} chars)"
    if key.startswith("AIza"):
        return f"standard key (AIza…, {len(key)} chars) — deprecated format"
    if key.startswith("ya29."):
        return "OAuth access token — not an API key"
    return f"unrecognised format ({key[:2]}…, {len(key)} chars)"


def _retry_after(payload: dict) -> float | None:
    for detail in payload.get("error", {}).get("details", []) or []:
        delay = detail.get("retryDelay")
        if delay:
            m = re.match(r"([\d.]+)s", str(delay))
            if m:
                return float(m.group(1))
    return None


def _is_daily(payload: dict) -> bool:
    text = str(payload)
    return "PerDay" in text or "per_day" in text.lower() or "daily" in text.lower()


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str, models: list[str], timeout: float = 120.0, session=None) -> None:
        super().__init__(models, timeout)
        self.api_key = api_key
        self.session = session or requests.Session()
        self._auth_failures = 0
        self._no_thinking: set[str] = set()
        self._no_json: set[str] = set()

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.models)

    def _body(self, model: str, req: GenerationRequest, thinking: bool) -> dict:
        config: dict = {"maxOutputTokens": req.max_output_tokens}
        if model not in self._no_json:
            config["responseMimeType"] = "application/json"
        if not model.startswith("gemini-3"):  # Gemini 3: Google recommends the default temperature
            config["temperature"] = req.temperature
        if thinking and model.startswith("gemini-3") and model not in self._no_thinking:
            config["thinkingConfig"] = {"thinkingLevel": "low"}
        return {
            "systemInstruction": {"parts": [{"text": req.system_prompt()}]},
            "contents": [{"role": "user", "parts": [{"text": req.user_prompt()}]}],
            "generationConfig": config,
        }

    def _post(self, model: str, body: dict) -> requests.Response:
        return self.session.post(
            ENDPOINT.format(model=model),
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json=body,
            timeout=self.timeout,
        )

    def _complete(self, model: str, req: GenerationRequest) -> str:
        body = self._body(model, req, thinking=True)
        for attempt in range(3):
            try:
                resp = self._post(model, body)
            except requests.RequestException as exc:
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise ProviderError(f"gemini network error: {exc}", retryable=True) from exc

            if resp.status_code == 200:
                return self._text_from(resp.json())

            try:
                payload = resp.json()
            except ValueError:
                payload = {"error": {"message": resp.text[:300]}}
            err = payload.get("error", {}) or {}
            message = str(err.get("message", ""))[:300]
            reason = " ".join(str(d.get("reason", "")) for d in err.get("details", []) or [])
            status = resp.status_code

            if status == 400 and "thinking" in message.lower() and "thinkingConfig" in body["generationConfig"]:
                self._no_thinking.add(model)
                body = self._body(model, req, thinking=False)
                continue
            if status == 400 and ("mime" in message.lower() or "json mode" in message.lower()) \
                    and "responseMimeType" in body["generationConfig"]:
                self._no_json.add(model)
                body = self._body(model, req, thinking=True)
                continue
            if status == 400 and ("API key not valid" in message or "API_KEY_INVALID" in reason):
                raise AuthError(f"Gemini rejected the API key: {message}", hint=KEY_HELP)
            if status == 400 and "location is not supported" in message.lower():
                raise AuthError(f"Gemini not available from this location: {message}")
            if status == 401:
                self._auth_failures += 1
                exc = ModelUnavailableError(f"gemini {model}: 401 {reason or 'UNAUTHENTICATED'} — {message}")
                exc.model_unavailable = True  # type: ignore[attr-defined]
                raise exc
            if status == 403:
                raise AuthError(f"Gemini permission denied ({reason or 'PERMISSION_DENIED'}): {message}",
                                hint="Enable the Generative Language API for the key's project or create a "
                                     "new key at https://aistudio.google.com/api-keys")
            if status == 404:
                exc = ModelUnavailableError(f"gemini model '{model}' not available: {message}")
                exc.model_unavailable = True  # type: ignore[attr-defined]
                raise exc
            if status == 429:
                wait = _retry_after(payload)
                if not _is_daily(payload) and wait and wait <= 20 and attempt < 2:
                    time.sleep(wait + 1)
                    continue
                raise QuotaError(f"gemini {model} quota: {message}", retry_after=wait)
            if status in (500, 502, 503, 504) and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            raise ProviderError(f"gemini {model} HTTP {status}: {message}", retryable=status >= 500)
        raise ProviderError(f"gemini {model}: retries exhausted", retryable=True)

    @staticmethod
    def _text_from(data: dict) -> str:
        feedback = data.get("promptFeedback", {}) or {}
        if feedback.get("blockReason"):
            raise ContentRejected(f"gemini blocked the prompt: {feedback['blockReason']}")
        candidates = data.get("candidates") or []
        if not candidates:
            raise ContentRejected("gemini returned no candidates")
        cand = candidates[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        finish = cand.get("finishReason", "")
        if not text.strip():
            raise ContentRejected(f"gemini returned empty text (finishReason={finish})")
        if finish in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
            raise ContentRejected(f"gemini stopped: {finish}")
        return text

    def generate(self, req: GenerationRequest) -> ArticleDraft:
        self._auth_failures = 0
        tried = 0
        last: Exception | None = None
        for model in self.models:
            if model in self.bad_models:
                continue
            tried += 1
            try:
                return parse_draft(self._complete(model, req), provider=self.name, model=model)
            except ModelUnavailableError as exc:
                self.bad_models.add(model)
                last = exc
                log.debug("%s", exc)
            except (QuotaError, ContentRejected, ProviderError) as exc:
                last = exc
                log.debug("gemini %s failed: %s", model, exc)
        if tried and self._auth_failures >= tried:
            raise AuthError(
                f"Gemini answered 401 UNAUTHENTICATED for every model ({', '.join(self.models)}). "
                f"Key type: {describe_key(self.api_key)}.",
                hint=KEY_HELP,
            )
        if last:
            raise last
        raise ProviderError("gemini: all configured models are unavailable for this key")
