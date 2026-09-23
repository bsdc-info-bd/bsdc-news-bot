"""Provider interface, prompt construction and robust response parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ContentRejected, ProviderError, QuotaError
from ..utils import normalize_space, short_hash, truncate

PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

SYSTEM_PROMPT = (
    "You are the senior news editor of '{site}', an English-language technology news site. "
    "You write accurate, original, well-structured news articles in a neutral journalistic tone. "
    "You never invent facts, quotes, numbers, names or dates that are not in the source material. "
    "You always answer with a single valid JSON object and nothing else."
)

DEFAULT_PROMPT = """Rewrite the SOURCE MATERIAL below into an original, fully structured news article for {site}.

RULES
1. Facts only from the source. Never invent quotes, numbers, names, dates or events. If something is uncertain, attribute it ("according to {source}").
2. Write {target_words}-{max_words} words in fresh wording — do not copy sentences verbatim (short attributed quotes are fine).
3. Structure: a strong lead paragraph (who/what/when/where/why), then 3-5 <h2> sections such as Key Details, Background, Why It Matters, What's Next. Use <h3>, <ul>/<ol> where useful.
4. Allowed HTML tags only: <p> <h2> <h3> <ul> <ol> <li> <strong> <em> <blockquote> <mark> <table> <thead> <tbody> <tr> <th> <td>. No links, no images, no inline styles, no markdown.
5. Remove promotional text, newsletter prompts, author bios and the original site's self-references.
6. Highlight at most 2 essential facts with <mark>.
7. Headline: specific, factual, max 90 characters, no clickbait, no ALL CAPS, no trailing period.
8. meta_description: 140-160 characters summarising the news.
9. key_points: 3-5 short factual bullet strings.
10. faq: 2-3 question/answer pairs a reader would search for, answered only from the source.
11. tags: 3-6 short topic tags (companies, products, technologies). category: one of {categories}.
12. focus_keyword: the main 2-4 word search phrase.

Return ONLY this JSON object:
{{"headline": "...", "meta_description": "...", "focus_keyword": "...", "category": "...",
 "tags": ["..."], "key_points": ["..."], "body_html": "<p>...</p>",
 "faq": [{{"q": "...", "a": "..."}}]}}

ORIGINAL HEADLINE: {title}
SOURCE: {source}
PUBLISHED: {published}
OTHER OUTLETS COVERING THIS STORY: {related}

SOURCE MATERIAL:
<<<
{text}
>>>"""


@dataclass
class GenerationRequest:
    title: str
    text: str
    source: str
    url: str
    published: str = ""
    related: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    site: str = "bsdc news"
    target_words: int = 750
    min_words: int = 450
    max_source_chars: int = 12000
    temperature: float = 0.6
    max_output_tokens: int = 8192
    prompt_template: str = ""
    feedback: str = ""  # quality-gate issues from a rejected previous draft

    def user_prompt(self) -> str:
        template = self.prompt_template or DEFAULT_PROMPT
        text = self.text
        if len(text) > self.max_source_chars:
            text = text[: self.max_source_chars].rsplit("\n", 1)[0]
        return template.format(
            site=self.site,
            title=self.title,
            source=self.source,
            published=self.published or "unknown",
            related=", ".join(self.related) or "none",
            text=text,
            target_words=self.target_words,
            max_words=self.target_words + 350,
            categories=", ".join(self.categories) or "Technology",
        ) + (f"\n\nIMPORTANT: your previous draft was rejected by the editor because: {self.feedback}. "
             "Fix every one of these problems in this new version." if self.feedback else "")

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT.format(site=self.site)


@dataclass
class ArticleDraft:
    headline: str
    body_html: str
    meta_description: str = ""
    focus_keyword: str = ""
    category: str = ""
    tags: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    faq: list[dict] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    ai_generated: bool = True


def load_prompt_template(path_hint: str = "") -> str:
    if path_hint:
        p = Path(path_hint)
        if not p.is_absolute():
            p = PROMPT_DIR.parent / path_hint
        if p.exists():
            return p.read_text(encoding="utf-8")
    return DEFAULT_PROMPT


_FENCE_RE = re.compile(r"^```(?:json|html)?\s*|\s*```$", re.I | re.M)


def _extract_json_block(text: str) -> str:
    text = _FENCE_RE.sub("", text.strip())
    start = text.find("{")
    if start == -1:
        return ""
    depth, in_str, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def _repair_json(raw: str) -> str:
    raw = re.sub(r",\s*([}\]])", r"\1", raw)  # trailing commas
    raw = raw.replace("\u201c", '"').replace("\u201d", '"') if raw.count('"') < 4 else raw
    return raw


def parse_draft(text: str, provider: str = "", model: str = "") -> ArticleDraft:
    """Parse model output into an ArticleDraft; accepts JSON or bare HTML."""
    if not text or not text.strip():
        raise ContentRejected("empty model response")
    block = _extract_json_block(text)
    data = None
    if block:
        for candidate in (block, _repair_json(block)):
            try:
                data = json.loads(candidate, strict=False)
                break
            except ValueError:
                continue
    if isinstance(data, dict) and (data.get("body_html") or data.get("body")):
        body = data.get("body_html") or data.get("body") or ""
        faq = []
        for item in data.get("faq") or []:
            if isinstance(item, dict):
                q = normalize_space(item.get("q") or item.get("question") or "")
                a = normalize_space(item.get("a") or item.get("answer") or "")
                if q and a:
                    faq.append({"q": q, "a": a})
        return ArticleDraft(
            headline=truncate(normalize_space(str(data.get("headline") or data.get("title") or "")), 110, ""),
            body_html=_FENCE_RE.sub("", str(body)).strip(),
            meta_description=normalize_space(str(data.get("meta_description") or data.get("description") or "")),
            focus_keyword=normalize_space(str(data.get("focus_keyword") or "")),
            category=normalize_space(str(data.get("category") or "")),
            tags=[normalize_space(str(t)) for t in (data.get("tags") or []) if str(t).strip()][:8],
            key_points=[normalize_space(str(k)) for k in (data.get("key_points") or []) if str(k).strip()][:6],
            faq=faq[:4],
            provider=provider,
            model=model,
        )
    # Bare HTML fallback (older prompt style)
    html_text = _FENCE_RE.sub("", text).strip()
    if "<p" in html_text.lower():
        return ArticleDraft(headline="", body_html=html_text, provider=provider, model=model)
    raise ContentRejected("model response was neither JSON nor HTML")


class AIProvider:
    """Base class. Subclasses implement ``_complete`` and return raw text."""

    name = "base"

    def __init__(self, models: list[str], timeout: float = 120.0) -> None:
        self.models = [m for m in models if m]
        self.timeout = timeout
        self.bad_models: set[str] = set()

    @property
    def available(self) -> bool:
        return bool(self.models)

    @property
    def fingerprint(self) -> str:
        """Non-reversible short hash of the credential (detects key rotation)."""
        key = getattr(self, "api_key", "") or ""
        return short_hash(key, 10) if key else ""

    def generate(self, req: GenerationRequest) -> ArticleDraft:
        last: Exception | None = None
        for model in self.models:
            if model in self.bad_models:
                continue
            try:
                raw = self._complete(model, req)
                return parse_draft(raw, provider=self.name, model=model)
            except QuotaError as exc:
                last = exc
                continue  # try the next model (quotas are per model)
            except ProviderError as exc:
                last = exc
                if getattr(exc, "model_unavailable", False):
                    self.bad_models.add(model)
                continue
            except ContentRejected as exc:
                last = exc
                continue
        if last:
            raise last
        raise ProviderError(f"{self.name}: no usable model configured")

    def _complete(self, model: str, req: GenerationRequest) -> str:  # pragma: no cover
        raise NotImplementedError
