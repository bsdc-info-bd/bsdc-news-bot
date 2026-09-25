"""FAQPage structured data.

Since 2023 Google only shows FAQ rich results for well-known, authoritative
government and health sites, but the markup still powers AI Overviews, Bing and
voice assistants — and invalid markup is a manual-action risk, so it is validated
here rather than trusted.
"""

from ...cortex.text.normalize import squish

MAX_ITEMS = 10
QUESTION_MAX = 200
ANSWER_MIN_WORDS = 6
ANSWER_MAX_WORDS = 120


def build(items: list[tuple[str, str]] | list[dict], *, limit: int = MAX_ITEMS) -> dict | None:
    """A FAQPage node from (question, answer) pairs or dicts."""
    nodes: list[dict] = []
    seen: set[str] = set()
    for item in items or []:
        question, answer = _pair(item)
        if not question or not answer:
            continue
        key = squish(question).lower()
        if key in seen:
            continue
        if len(answer.split()) < ANSWER_MIN_WORDS:
            continue                       # a thin answer is worse than no markup
        seen.add(key)
        nodes.append({
            "@type": "Question",
            "name": squish(question)[:QUESTION_MAX],
            "acceptedAnswer": {"@type": "Answer", "text": _clip(squish(answer))},
        })
        if len(nodes) >= limit:
            break
    if not nodes:
        return None
    return {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": nodes}


def _pair(item) -> tuple[str, str]:
    if isinstance(item, dict):
        question = str(item.get("question") or item.get("q") or item.get("name") or "")
        answer = str(item.get("answer") or item.get("a") or item.get("text") or "")
        return squish(question), squish(answer)
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return squish(str(item[0])), squish(str(item[1]))
    return "", ""


def _clip(text: str) -> str:
    words = text.split()
    if len(words) > ANSWER_MAX_WORDS:
        return " ".join(words[:ANSWER_MAX_WORDS]).rstrip(",;:") + "."
    return text


def validate(node: dict | None) -> list[str]:
    problems: list[str] = []
    if not node:
        return ["no FAQ node"]
    entities = node.get("mainEntity") or []
    if not entities:
        problems.append("FAQPage has no questions")
    if len(entities) > MAX_ITEMS:
        problems.append(f"{len(entities)} questions exceeds the {MAX_ITEMS} limit")
    for entity in entities:
        if entity.get("@type") != "Question":
            problems.append("mainEntity item is not a Question")
        if not squish(str(entity.get("name", ""))):
            problems.append("a question has no name")
        answer = (entity.get("acceptedAnswer") or {}).get("text", "")
        if len(str(answer).split()) < ANSWER_MIN_WORDS:
            problems.append(f"answer too short for: {str(entity.get('name'))[:40]}")
        if "<" in str(answer) or "&" in str(answer):
            problems.append("answer contains raw markup; escape it first")
    return problems


def questions_only(node: dict | None) -> list[str]:
    if not node:
        return []
    return [str(entity.get("name", "")) for entity in node.get("mainEntity", [])]


def to_visible_html(items: list[tuple[str, str]], *, heading: str = "Frequently asked questions",
                    details: bool = True) -> str:
    """The on-page FAQ block that must match the markup exactly."""
    rows: list[str] = []
    for question, answer in items or []:
        question, answer = squish(question), squish(answer)
        if not question or not answer:
            continue
        if details:
            rows.append(f'<details class="bsd-faq-item"><summary>{_esc(question)}</summary>'
                        f'<p>{_esc(answer)}</p></details>')
        else:
            rows.append(f'<div class="bsd-faq-item"><h3>{_esc(question)}</h3>'
                        f'<p>{_esc(answer)}</p></div>')
    if not rows:
        return ""
    return f'<section class="bsd-faq"><h2>{_esc(heading)}</h2>{"".join(rows)}</section>'


def _esc(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
