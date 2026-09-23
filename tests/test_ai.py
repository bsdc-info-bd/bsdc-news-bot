import json

import pytest

from bsdc_news.ai.base import GenerationRequest, parse_draft
from bsdc_news.ai.gemini import GeminiProvider, describe_key
from bsdc_news.ai.openai_compat import GroqProvider
from bsdc_news.ai.router import AIRouter, build_router
from bsdc_news.errors import AuthError, ContentRejected
from bsdc_news.settings import load_settings
from bsdc_news.state import State

from .conftest import FakeResp

UNAUTH = {"error": {"code": 401, "status": "UNAUTHENTICATED",
                    "message": "Request had invalid authentication credentials. Expected OAuth 2 access token...",
                    "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                 "reason": "ACCESS_TOKEN_TYPE_UNSUPPORTED"}]}}
GOOD_JSON = json.dumps({"headline": "Nvidia unveils Rubin Ultra", "body_html": "<p>Body</p>",
                        "meta_description": "desc", "tags": ["Nvidia"], "key_points": ["a"],
                        "faq": [{"q": "Q?", "a": "A."}], "category": "AI"})


def gemini_ok(text=GOOD_JSON):
    return FakeResp(200, json.dumps({"candidates": [{"content": {"parts": [{"text": text}]},
                                                     "finishReason": "STOP"}]}))


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        resp = self.responses.pop(0)
        return resp(url) if callable(resp) else resp


REQ = GenerationRequest(title="Nvidia unveils chip", text="Nvidia said... " * 50, source="Example", url="https://e.com")


def test_parse_draft_handles_fences_trailing_commas_and_html():
    d = parse_draft("```json\n" + GOOD_JSON[:-1] + ',}\n```')
    assert d.headline == "Nvidia unveils Rubin Ultra" and d.faq == [{"q": "Q?", "a": "A."}]
    html_only = parse_draft("```html\n<h2>Hi</h2><p>Text</p>\n```")
    assert html_only.body_html.startswith("<h2>") and html_only.headline == ""
    with pytest.raises(ContentRejected):
        parse_draft("I cannot help with that.")


def test_gemini_rotates_models_after_401_and_sends_header_key():
    session = Session([FakeResp(401, json.dumps(UNAUTH)), gemini_ok()])
    p = GeminiProvider("AQ.test-key", ["gemini-2.5-flash", "gemini-3.6-flash"], session=session)
    draft = p.generate(REQ)
    assert draft.model == "gemini-3.6-flash" and draft.provider == "gemini"
    assert session.calls[0]["headers"]["x-goog-api-key"] == "AQ.test-key"
    assert "key=" not in session.calls[0]["url"]  # key never in URL/logs
    body = session.calls[1]["json"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert "gemini-2.5-flash" in p.bad_models


def test_gemini_all_401_raises_auth_error_with_fix_hint():
    session = Session([FakeResp(401, json.dumps(UNAUTH))] * 3)
    p = GeminiProvider("AIzaSyOLDKEY0000000000000000000000000000", ["m1", "m2", "m3"], session=session)
    with pytest.raises(AuthError) as exc:
        p.generate(REQ)
    text = exc.value.describe()
    assert "401" in text and "aistudio.google.com" in text and "standard key" in text


def test_gemini_retries_without_thinking_when_unsupported():
    bad = FakeResp(400, json.dumps({"error": {"message": "thinking level is not supported for this model"}}))
    session = Session([bad, gemini_ok()])
    p = GeminiProvider("AQ.k", ["gemini-3.5-flash-lite"], session=session)
    p.generate(REQ)
    assert "thinkingConfig" not in session.calls[1]["json"]["generationConfig"]


def test_gemini_quota_moves_to_next_model(monkeypatch):
    quota = FakeResp(429, json.dumps({"error": {"message": "Quota exceeded GenerateRequestsPerDayPerProjectPerModel"}}))
    session = Session([quota, gemini_ok()])
    p = GeminiProvider("AQ.k", ["a", "b"], session=session)
    assert p.generate(REQ).model == "b"


def test_describe_key_never_leaks_value():
    assert describe_key("AQ.Ab123456789") == "auth key (AQ.…, 14 chars)"
    assert "deprecated" in describe_key("AIzaSy" + "x" * 33)
    assert describe_key("") == "missing"


def test_groq_openai_compatible_and_json_mode_fallback():
    ok = FakeResp(200, json.dumps({"choices": [{"message": {"content": GOOD_JSON}}]}))
    no_json = FakeResp(400, '{"error":{"message":"response_format json_object not supported"}}')
    session = Session([no_json, ok])
    p = GroqProvider("gsk_test", ["openai/gpt-oss-120b"], session=session)
    d = p.generate(REQ)
    assert d.provider == "groq" and session.calls[0]["json"]["response_format"] == {"type": "json_object"}
    assert "response_format" not in session.calls[1]["json"]
    assert session.calls[1]["headers"]["Authorization"] == "Bearer gsk_test"


def test_router_fails_over_and_pauses_broken_provider(tmp_path):
    state = State.load(tmp_path / "s.json")
    bad = GeminiProvider("AQ.k", ["m1"], session=Session([FakeResp(403, json.dumps(
        {"error": {"message": "denied", "details": [{"reason": "PERMISSION_DENIED"}]}}))]))
    good = GroqProvider("gsk", ["x"], session=Session([FakeResp(200, json.dumps(
        {"choices": [{"message": {"content": GOOD_JSON}}]}))]))
    router = AIRouter([bad, good], state)
    draft = router.generate(REQ)
    assert draft.provider == "groq"
    assert "gemini" in router.auth_errors
    assert state.provider_disabled("gemini")
    assert router.active_providers() == [good]


def test_router_budget_and_all_fail_returns_none(tmp_path):
    class Boom(GroqProvider):
        def generate(self, req):
            raise RuntimeError("unexpected")

    router = AIRouter([Boom("k", ["m"])], State.load(tmp_path / "s.json"), max_calls=1)
    assert router.generate(REQ) is None
    assert router.generate(REQ) is None  # budget exhausted, no crash
    assert router.calls == 1


def test_build_router_skips_providers_without_keys():
    s = load_settings(env={"GROQ_API_KEY": "gsk_x"})
    router = build_router(s)
    assert [p.name for p in router.providers] == ["groq"]
    assert not build_router(load_settings(env={})).enabled


def test_groq_request_fits_free_tier_limits():
    ok = FakeResp(200, json.dumps({"choices": [{"message": {"content": GOOD_JSON}}]}))
    session = Session([ok])
    big = GenerationRequest(title="T", text="word " * 6000, source="S", url="https://e.com", max_output_tokens=8192)
    GroqProvider("gsk", ["openai/gpt-oss-120b"], session=session).generate(big)
    body = session.calls[0]["json"]
    assert body["max_tokens"] <= 3800 and body["reasoning_effort"] == "low"
    assert len(body["messages"][1]["content"]) < 9000 + 4000  # source truncated + instructions


def test_gemini3_uses_default_temperature_and_json_fallback():
    no_json = FakeResp(400, json.dumps({"error": {"message": "JSON mode is not enabled for this model"}}))
    session = Session([no_json, gemini_ok()])
    GeminiProvider("AQ.k", ["gemini-3.6-flash"], session=session).generate(REQ)
    first, second = (c["json"]["generationConfig"] for c in session.calls)
    assert "temperature" not in first and first["responseMimeType"] == "application/json"
    assert "responseMimeType" not in second
    s2 = Session([gemini_ok()])
    GeminiProvider("AQ.k", ["gemini-2.5-flash-lite"], session=s2).generate(REQ)
    assert s2.calls[0]["json"]["generationConfig"]["temperature"] == REQ.temperature
