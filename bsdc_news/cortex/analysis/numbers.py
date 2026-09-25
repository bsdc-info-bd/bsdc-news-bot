"""Numeric intelligence: money, percentages, quantities, dates and deltas.

Numbers are the most shareable part of a tech story and the most valuable
keyword surface ("288GB HBM", "$1,999", "40% faster"), so they are extracted,
normalised and ranked separately from prose.
"""

import re
from dataclasses import dataclass

MULTIPLIERS = {"k": 1_000, "m": 1_000_000, "bn": 1_000_000_000, "b": 1_000_000_000,
               "n": 1_000_000_000, "t": 1_000_000_000_000, "trillion": 1_000_000_000_000,
               "billion": 1_000_000_000, "million": 1_000_000, "thousand": 1_000,
               "lakh": 100_000, "crore": 10_000_000}
UNITS = {"gb", "tb", "mb", "kb", "pb", "ghz", "mhz", "thz", "w", "kw", "mw", "mah",
         "wh", "nm", "mm", "cm", "m", "km", "in", "inch", "inches", "ft", "feet",
         "kg", "g", "lb", "lbs", "oz", "ml", "l", "hz", "fps", "dpi", "ppi", "nits",
         "cd", "ms", "s", "sec", "mins", "min", "hrs", "hr", "h", "cores", "threads",
         "users", "downloads", "units", "people", "tokens", "parameters", "params"}
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items()) if len(m) > 3})

# Long scale words must be tried before the single letters, otherwise "billion"
# matches as "b" and the reported figure loses its unit.
_MONEY = re.compile(
    r"(?P<symbol>[$€£¥₹৳])\s?(?P<amount>[\d,]+(?:\.\d+)?)\s?"
    r"(?P<suffix>billion|million|thousand|trillion|crore|lakh|bn|[kmbnt])\b"
    r"|(?P<symbol2>[$€£¥₹৳])\s?(?P<amount2>[\d,]+(?:\.\d+)?)", re.IGNORECASE)
_MONEY_WORDS = re.compile(r"(?P<amount>[\d,]+(?:\.\d+)?)\s?(?P<suffix>billion|million|thousand|trillion|crore|lakh)?\s+(?P<currency>dollars|euros|pounds|yen|rupees|taka|usd|eur|gbp|bdt)", re.IGNORECASE)
_PERCENT = re.compile(r"(?P<amount>\d+(?:\.\d+)?)\s?(?:%|per ?cent|percent)", re.IGNORECASE)
_MEASURE = re.compile(r"\b(?P<amount>\d+(?:\.\d+)?)\s?(?P<unit>" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")\b", re.IGNORECASE)
_MULTIPLIER = re.compile(r"\b(?P<amount>\d+(?:\.\d+)?)\s?(?:x|×|times)\b", re.IGNORECASE)
_DATE = re.compile(
    r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{4}))?\b"
    r"|\b(?P<day2>\d{1,2})[-/](?P<month2>\d{1,2})[-/](?P<year2>\d{2,4})\b"
    r"|\b(?P<year3>\d{4})-(?P<month3>\d{2})-(?P<day3>\d{2})\b", re.IGNORECASE)
_RELATIVE_DATE = re.compile(r"\b(today|tonight|tomorrow|yesterday|tonight|this week|next week|last week|"
                            r"this month|next month|last month|this year|next year|last year|"
                            r"q[1-4](?:\s?\d{4})?|\d{1,2}(?:st|nd|rd|th)? quarter)\b", re.IGNORECASE)
_RANGE = re.compile(r"(?P<low>\d[\d,\.]*)\s?(?:-|–|to)\s?(?P<high>\d[\d,\.]*)\s?(?P<unit>%|[a-z]{1,6})?")


@dataclass
class Number:
    text: str
    kind: str             # money | percent | measure | multiplier | date | count | range
    value: float = 0.0
    unit: str = ""
    position: float = 1.0

    def phrase(self) -> str:
        return self.text.strip()


def _to_float(raw: str) -> float:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return 0.0


def extract(text: str) -> list[Number]:
    """Every numeric fact in a document, normalised and positioned."""
    if not text:
        return []
    length = max(1, len(text))
    out: list[Number] = []

    def add(match: re.Match, kind: str, value: float, unit: str = "") -> None:
        out.append(Number(text=match.group(0).strip(), kind=kind, value=value, unit=unit,
                          position=round(match.start() / length, 4)))

    for match in _MONEY.finditer(text):
        raw_amount = match.group("amount") or match.group("amount2") or ""
        if not raw_amount:
            continue
        amount = _to_float(raw_amount)
        suffix = (match.group("suffix") or "").lower()
        amount *= MULTIPLIERS.get(suffix, 1)
        add(match, "money", amount, match.group("symbol") or match.group("symbol2") or "")
    for match in _MONEY_WORDS.finditer(text):
        amount = _to_float(match.group("amount"))
        amount *= MULTIPLIERS.get((match.group("suffix") or "").lower(), 1)
        add(match, "money", amount, match.group("currency").lower())
    for match in _PERCENT.finditer(text):
        add(match, "percent", _to_float(match.group("amount")), "%")
    for match in _MEASURE.finditer(text):
        add(match, "measure", _to_float(match.group("amount")), match.group("unit").lower())
    for match in _MULTIPLIER.finditer(text):
        add(match, "multiplier", _to_float(match.group("amount")), "x")
    for match in _RANGE.finditer(text):
        low, high = _to_float(match.group("low")), _to_float(match.group("high"))
        if high > low:
            add(match, "range", high - low, (match.group("unit") or "").strip())
    for match in _DATE.finditer(text):
        add(match, "date", 0.0, "")
    return out


def relative_dates(text: str) -> list[str]:
    return [match.group(0).lower() for match in _RELATIVE_DATE.finditer(text)]


def parse_date(text: str) -> tuple[int, int, int] | None:
    """(year, month, day) from a matched date span, or None."""
    match = _DATE.search(text or "")
    if not match:
        return None
    groups = match.groupdict()
    if groups.get("month"):
        month = MONTHS.get(groups["month"].lower()[:3], 0)
        return (int(groups["year"] or 0), month, int(groups["day"]))
    if groups.get("year3"):
        return (int(groups["year3"]), int(groups["month3"]), int(groups["day3"]))
    if groups.get("year2"):
        year = int(groups["year2"])
        return ((2000 + year) if year < 100 else year, int(groups["month2"]), int(groups["day2"]))
    return None


def money_phrase(value: float, symbol: str = "$") -> str:
    """Human money formatting: $1.2bn, $3.4m, $1,999."""
    if value >= 1e12:
        return f"{symbol}{value / 1e12:.1f}tn"
    if value >= 1e9:
        return f"{symbol}{value / 1e9:.1f}bn"
    if value >= 1e6:
        return f"{symbol}{value / 1e6:.1f}m"
    if value >= 1e3 and value % 1e3 == 0:
        return f"{symbol}{int(value / 1e3)}k"
    return f"{symbol}{value:,.0f}" if value >= 1000 else f"{symbol}{value:g}"


def summarise(numbers: list[Number]) -> dict:
    """Aggregate view used by the writer and the SEO layer."""
    by_kind: dict[str, list[Number]] = {}
    for number in numbers:
        by_kind.setdefault(number.kind, []).append(number)
    lead = [number for number in numbers if number.position < 0.25]
    return {
        "total": len(numbers),
        "kinds": {kind: len(items) for kind, items in by_kind.items()},
        "lead_numbers": [number.phrase() for number in lead[:5]],
        "money_total": sum(number.value for number in by_kind.get("money", [])),
        "max_percent": max((number.value for number in by_kind.get("percent", [])), default=0.0),
        "phrases": [number.phrase() for number in sorted(numbers, key=lambda n: n.position)[:12]],
    }


def numeric_density(text: str) -> float:
    """Numbers per 100 words — a concrete-writing signal for the quality gate."""
    tokens = re.findall(r"\w+", text or "")
    if not tokens:
        return 0.0
    return round(len(extract(text)) / len(tokens) * 100, 2)
