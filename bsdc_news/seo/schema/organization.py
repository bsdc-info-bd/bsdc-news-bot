"""Publisher and site identity: Organization, WebSite and SearchAction.

The publisher node is what earns the "Top Stories" publisher logo treatment, and a
WebSite node with a potentialAction is what enables the sitelinks search box.
"""

from ...cortex.text.normalize import squish


def organization(*, name: str, url: str = "", logo_url: str = "", description: str = "",
                 same_as: list[str] | None = None, email: str = "", founding_date: str = "",
                 country: str = "BD", language: str = "en",
                 type_: str = "NewsMediaOrganization") -> dict | None:
    name = squish(name)
    if not name:
        return None
    node: dict = {"@context": "https://schema.org", "@type": type_, "name": name}
    if url:
        node["url"] = squish(url)
    if description:
        node["description"] = squish(description)[:300]
    if logo_url:
        node["logo"] = {"@type": "ImageObject", "url": squish(logo_url),
                        "width": 600, "height": 600}
    if same_as:
        node["sameAs"] = [squish(item) for item in same_as if item][:10]
    if email:
        node["contactPoint"] = {"@type": "ContactPoint", "email": squish(email),
                                  "contactType": "editorial", "availableLanguage": language}
    if founding_date:
        node["foundingDate"] = squish(founding_date)
    if country:
        node["address"] = {"@type": "PostalAddress", "addressCountry": squish(country)}
    node["publishingPrinciples"] = squish(url).rstrip("/") + "/p/editorial-policy.html" if url else ""
    if not node["publishingPrinciples"]:
        node.pop("publishingPrinciples")
    return node


def website(*, name: str, url: str = "", alternate: list[str] | None = None,
            description: str = "", search_url: str = "", language: str = "en",
            publisher: dict | None = None) -> dict | None:
    name = squish(name)
    if not name:
        return None
    node: dict = {"@context": "https://schema.org", "@type": "WebSite", "name": name,
                  "inLanguage": language}
    if url:
        node["url"] = squish(url)
    if alternate:
        node["alternateName"] = [squish(item) for item in alternate if item][:5]
    if description:
        node["description"] = squish(description)[:300]
    if search_url and "{search_term_string}" in search_url:
        node["potentialAction"] = {
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint",
                       "urlTemplate": squish(search_url)},
            "query-input": "required name=search_term_string",
        }
    if publisher:
        node["publisher"] = publisher
    return node


def validate(node: dict | None) -> list[str]:
    problems: list[str] = []
    if not node:
        return ["no organization node"]
    if not node.get("name"):
        problems.append("missing name")
    if node.get("@type") in {"Organization", "NewsMediaOrganization"} and not node.get("url"):
        problems.append("a publisher should declare its url")
    if node.get("@type") in {"Organization", "NewsMediaOrganization"} and not node.get("logo"):
        problems.append("a publisher logo is required for news rich results")
    for url in node.get("sameAs", []) or []:
        if not str(url).startswith("http"):
            problems.append(f"sameAs must be absolute: {url}")
    return problems


def same_as_from_settings(settings) -> list[str]:
    """Collect social profile URLs from the settings object, if present."""
    urls: list[str] = []
    for attribute in ("facebook_url", "twitter_url", "x_url", "youtube_url", "linkedin_url",
                      "instagram_url", "github_url", "pinterest_url", "telegram_url"):
        value = getattr(settings, attribute, "") or ""
        value = squish(str(value))
        if value.startswith("http"):
            urls.append(value)
    return urls
