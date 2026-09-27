"""robots.txt generation and crawl-budget policy.

The file is generated rather than hand-edited so the sitemap location, the crawl
delays and the blocked query patterns always match the current settings. Blocking
search/label/archive URLs is the single biggest crawl-budget win on Blogger.
"""

from ..cortex.text.normalize import squish

GOOD_BOTS = ("Googlebot", "Googlebot-News", "Googlebot-Image", "Bingbot", "Slurp",
             "DuckDuckBot", "Baiduspider", "YandexBot", "Applebot", "facebookexternalhit",
             "Twitterbot", "LinkedInBot", "WhatsApp", "TelegramBot", "Pinterestbot")
BAD_BOTS = ("AhrefsBot", "SemrushBot", "MJ12bot", "DotBot", "PetalBot", "DataForSeoBot",
            "Bytespider", "ClaudeBot-Search", "GPTBot", "CCBot", "Scrapy", "libwww-perl",
            "python-requests", "curl", "wget")
# Only real paths belong in Disallow: the mobile-parameter duplicates are handled by
# the canonical tag, and both Google and a validator reject "?m=0" as a path.
BLOGGER_BLOCK = ("/search", "/archive", "/feeds/comments/", "/*?updated-max*",
                 "/*?max-results*", "/*?m=*")


def build(*, site_url: str = "", sitemap_urls: list[str] | None = None,
          blocked_paths: list[str] | None = None, allow_all: bool = False,
          crawl_delay: int = 0, block_bad_bots: bool = True,
          extra: str = "") -> str:
    """A complete robots.txt."""
    site_url = squish(site_url).rstrip("/")
    sitemap_urls = [url for url in (sitemap_urls or []) if url]
    blocked = list(dict.fromkeys([*BLOGGER_BLOCK, *(blocked_paths or [])]))
    lines: list[str] = []

    if block_bad_bots:
        for bot in BAD_BOTS:
            lines += [f"User-agent: {bot}", "Disallow: /", ""]

    lines.append("User-agent: *")
    if allow_all:
        lines.append("Allow: /")
    else:
        for path in blocked:
            lines.append(f"Disallow: {path}")
        lines += ["Allow: /", "Allow: /*.html"]
    if crawl_delay:
        lines.append(f"Crawl-delay: {crawl_delay}")
    lines.append("")

    for bot in GOOD_BOTS:
        lines += [f"User-agent: {bot}", "Allow: /"]
        for path in ("/search", "/archive"):
            lines.append(f"Disallow: {path}")
        if crawl_delay:
            lines.append(f"Crawl-delay: {max(1, crawl_delay // 2)}")
        lines.append("")

    if site_url:
        lines.append(f"Host: {site_url.removeprefix('https://').removeprefix('http://')}")
    for url in sitemap_urls:
        lines.append(f"Sitemap: {url}")
    if extra.strip():
        lines += ["", extra.strip()]
    return "\n".join(lines).rstrip() + "\n"


def validate(text: str) -> list[str]:
    """Syntax and policy checks on a robots.txt."""
    problems: list[str] = []
    if not text.strip():
        return ["empty robots.txt"]
    seen_agent = False
    for raw in text.splitlines():
        line = squish(raw)
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            problems.append(f"malformed line: {line[:50]}")
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        lowered = key.lower()
        if lowered == "user-agent":
            seen_agent = True
            if not value:
                problems.append("empty User-agent value")
        elif lowered in {"disallow", "allow"}:
            if not seen_agent:
                problems.append(f"{key} appears before any User-agent")
            if value and not value.startswith("/"):
                problems.append(f"{key} path must start with /: {value[:40]}")
        elif lowered == "sitemap":
            if not value.startswith("http"):
                problems.append(f"Sitemap must be absolute: {value[:40]}")
        elif lowered not in {"crawl-delay", "host", "noindex", "request-rate", "clean-param"}:
            problems.append(f"unknown directive: {key}")
    if not seen_agent:
        problems.append("no User-agent block")
    if "Disallow: /" in text and "User-agent: *" in text:
        star_block = text.split("User-agent: *", 1)[1].split("User-agent", 1)[0]
        if "\nDisallow: /\n" in f"\n{star_block.strip()}\n":
            problems.append("wildcard agent is blocked from the whole site")
    return problems


def sitemap_declared(text: str) -> list[str]:
    """Sitemap URLs declared in a robots.txt."""
    return [squish(line.split(":", 1)[1]) for line in text.splitlines()
            if squish(line).lower().startswith("sitemap:")]


def allows(text: str, path: str, *, agent: str = "*") -> bool:
    """Does this robots.txt permit crawling `path` for `agent`?"""
    rules: list[tuple[str, bool]] = []
    current: list[str] = []
    for raw in text.splitlines():
        line = squish(raw)
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        lowered = key.lower()
        if lowered == "user-agent":
            if current and rules:
                if agent.lower() in [item.lower() for item in current] or "*" in current:
                    break
                rules = []
            current.append(value)
        elif lowered in {"allow", "disallow"} and value:
            rules.append((value, lowered == "allow"))
    if agent.lower() not in [item.lower() for item in current] and "*" not in current:
        rules = []
    best, allowed = "", True
    for pattern, is_allow in rules:
        if _matches(pattern, path) and len(pattern) > len(best):
            best, allowed = pattern, is_allow
    return allowed


def _matches(pattern: str, path: str) -> bool:
    if pattern.endswith("*"):
        return path.startswith(pattern[:-1])
    if "*" in pattern:
        head, _, tail = pattern.partition("*")
        return path.startswith(head) and (not tail or tail in path)
    return path.startswith(pattern)
